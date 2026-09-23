import os.path
import base64
import re
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scopes needed for Gmail API
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

# Use the labels seen in the notebook
PROCESSED_LABEL_ID = 'Label_4550656612000604041' # 'temp3 - processed'
MOCK_CATEGORY_LABEL_ID = 'Label_6075941912103430332' # 'temp2 - okay'

def get_service():
    """Authenticates and returns the Gmail API service."""
    creds = None
    if os.path.exists("gcp/token.json"):
        creds = Credentials.from_authorized_user_file("gcp/token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "gcp/credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("gcp/token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def clean_email_body(raw_content):
    """
    Removes HTML, CSS, hidden characters, shortens URLs.
    Based on the logic in untitled.ipynb.
    """
    if not raw_content:
        return ""

    # html tags and css/style blocks
    soup = BeautifulSoup(raw_content, "html.parser")

    # <style>, <script>, and <link> tags
    for element in soup(["style", "script", "link"]):
        element.decompose()

    text = soup.get_text(separator=' ')
    text = text.replace('\u200c', '').replace('\xa0', ' ')

    # url handling
    def url_cleaner(match):
        url = match.group(0)
        if len(url) > 60:
            return "[URL]"
        return url

    # replace long URLs
    text = re.sub(r'https?://\S+', url_cleaner, text)

    # replaces multiple newlines, spaces with a single one
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r' +', ' ', text)

    return text.strip()

def get_email_text(payload):
    """Recursively extracts the text content from the email payload."""
    text_content = ""

    if 'data' in payload.get('body', {}):
        data = payload['body']['data']
        # The data is base64url encoded
        text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        text_content += text + "\n"

    if 'parts' in payload:
        for part in payload['parts']:
            mime_type = part.get('mimeType')
            if mime_type == 'text/plain' or mime_type == 'text/html':
                data = part['body'].get('data')
                if data:
                    text_content += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore') + "\n"
            elif 'parts' in part:
                text_content += get_email_text(part)

    return text_content

def mock_blackbox_classify(subject, sender, text_content):
    """
    Mock classification function.
    In reality, this would call an LLM (e.g. Deepseek)
    and return the determined label ID based on content.
    """
    print(f"  [Mock] Classifying email '{subject}' from {sender}...")
    # Just returning a mock category label for now
    return MOCK_CATEGORY_LABEL_ID

def process_emails(service):
    """
    Fetches emails from the last 24 hours, filters out already processed ones,
    extracts their text, categorizes them, and applies labels.
    """
    # Gmail search syntax: newer_than:1d
    query = "newer_than:1d"

    print(f"Searching for messages with query: '{query}'")
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])

    if not messages:
        print("No new messages found.")
        return

    print(f"Found {len(messages)} messages in the search results.")

    processed_count = 0
    for msg_meta in messages:
        msg_id = msg_meta['id']
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()

        label_ids = msg.get('labelIds', [])

        # Skip if already processed
        if PROCESSED_LABEL_ID in label_ids:
            continue

        print(f"\nProcessing message ID: {msg_id}")

        headers = msg['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown Sender")

        print(f"  Subject: {subject}")
        print(f"  From: {sender}")

        # Extract and clean text
        raw_text = get_email_text(msg['payload'])
        cleaned_text = clean_email_body(raw_text)

        # Determine category label using the blackbox function
        category_label_id = mock_blackbox_classify(subject, sender, cleaned_text)

        # Apply labels (category and "LLM Processed")
        body = {
            'addLabelIds': [PROCESSED_LABEL_ID, category_label_id]
        }

        print(f"  Applying labels: {body['addLabelIds']}")
        service.users().messages().modify(
            userId='me',
            id=msg_id,
            body=body
        ).execute()

        processed_count += 1

    print(f"\nDone! Processed and labeled {processed_count} new messages.")

if __name__ == '__main__':
    print("Starting cron labeler...")
    try:
        service = get_service()
        process_emails(service)
    except Exception as e:
        print(f"An error occurred: {e}")
