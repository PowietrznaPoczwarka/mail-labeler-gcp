import os.path
import base64
import re
import logging
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from typesafe_sdk import Choice, TypeSafeClient

logger = logging.getLogger("cron_labeler")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("logs/cron_labeler.log")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Scopes needed for Gmail API
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

LABEL_IDS = {
    'IMPORTANT': 'Label_191074900200250148', # 👹 Pilne/Ważne
    'SPAM': 'Label_1970431896466590113', # 🤢 Spam
    'AWAITING_RESPONSE': 'Label_3347196074444027717', # 🎃 Do odpowiedzi
    'OTHER': 'Label_3725959684110416048', # 👽 Inne
    'SUBSCRIPTIONS': 'Label_9020177853318762020', # 🫥 Subskrypcje/Info/Oferty
    'UNPROCESSABLE': 'Label_4239649511002813377', # unprocessable
    'PROCESSED': 'Label_4550656612000604041', # processed
    'MOCK': 'Label_6075941912103430332', # temp
}

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

def should_classify(subject, sender, size_estimate):
    # TODO implement filtering based on subject and sender
    """
    Filtering function based on subject, sender, and size estimate. Currently judges only by size_estimate: skips classification if > 50000.
    """
    if size_estimate is not None and size_estimate > 50000:
        return False
    return True

def mock_blackbox_classify(subject, sender, text_content):
    """
    Mock classification function. In reality, this would call a classification model (or LLM?) and return the determined label ID based on content.
    """
    logger.info("Classifying email '%s' from %s", subject, sender)
    # Just returning a mock category label for now
    return LABEL_IDS['MOCK']

def classify_email_jev(subject, sender, text_content):
    """
    Classifies an email using TypeSafe's Jev AI model and returns the corresponding label ID.
    """
    logger.info("Classifying email '%s' from %s", subject, sender)
    email_context = f"Sender: {sender}\nSubject: {subject}\n\nEmail Body:\n{text_content}"
    
    try:
        with TypeSafeClient() as client:
            response = client.system_one(
                state=email_context,
                questions={
                    "category": Choice(
                        instructions="Categorize this email into one of the available groups.",
                        criteria={
                            "IMPORTANT": "Important emails I should read and pay attention to (but not necessarily answer).",
                            "SPAM": "Spam emails, unwanted junk, scams.",
                            "AWAITING_RESPONSE": "Emails that explicitly expect me to answer, reply, or take action.",
                            "SUBSCRIPTIONS": "Boring stuff, newsletters, repeated notifications, automated updates, or promotional offers.",
                            "OTHER": "Any email that does not fit into the other categories.",
                        },
                    ),
                },
            )
        chosen_category = response.answers["category"].choice
        return LABEL_IDS.get(chosen_category, LABEL_IDS['OTHER'])
        
    except Exception as e:
        logger.error("Error during TypeSafe classification for email '%s': %s", subject, str(e))
        return LABEL_IDS['UNPROCESSABLE']

def process_emails(service):
    """
    Fetches emails from the last 24 hours, filters out already processed ones, extracts text, categorizes, and applies labels.
    """
    # Gmail search syntax: newer_than:1d
    query = "newer_than:1d"
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])
    logger.info("Found %d new emails in search results with query '%s'", len(messages), query)

    if not messages:
        logger.info("Done processing. 0 messages processed.")
        return

    processed_count = 0
    for msg_meta in messages:
        msg_id = msg_meta['id']
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        label_ids = msg.get('labelIds', [])

        # Skip if already processed
        if LABEL_IDS['PROCESSED'] in label_ids:
            continue

        headers = msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown Sender")
        size_estimate = msg.get('sizeEstimate')

        if not should_classify(subject, sender, size_estimate):
            logger.info("Processed message %s: skipped classification (size_estimate: %s), applied unprocessable label", msg_id, size_estimate)
            body = {'addLabelIds': [LABEL_IDS['PROCESSED'], LABEL_IDS['UNPROCESSABLE']]}
        else:
            # Extract and clean text
            raw_text = get_email_text(msg.get('payload', {}))
            cleaned_text = clean_email_body(raw_text)
            # category_label_id = mock_blackbox_classify(subject, sender, cleaned_text)
            category_label_id = classify_email_jev(subject, sender, cleaned_text)
            body = {'addLabelIds': [LABEL_IDS['PROCESSED'], category_label_id]}
            logger.info("Processed message %s: classified with label %s", msg_id, category_label_id)

        service.users().messages().modify(userId='me', id=msg_id, body=body).execute()
        processed_count += 1
    logger.info("Done processing. Processed %d messages.", processed_count)

if __name__ == '__main__':
    logger.info("Starting cron labeler...")
    try:
        service = get_service()
        process_emails(service)
    except Exception as e:
        logger.exception("An error occurred: %s", e)
