import os

from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from datetime import datetime

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

PROJECT_ID = os.getenv('GCP_PROJECT_ID')
TOPIC_NAME = os.getenv('GCP_TOPIC_NAME')

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def start_watch():
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    
    service = build('gmail', 'v1', credentials=creds)
    topic = f'projects/{PROJECT_ID}/topics/{TOPIC_NAME}'
    
    request = {
        'labelIds': ['INBOX'],
        'topicName': topic
    }
    
    res = service.users().watch(userId='me', body=request).execute()
    print(f"Watch response: {res}")
    print(f"Expiration: {datetime.fromtimestamp(float(res.get('expiration')) / 1000.0)}")
    print(f"History ID: {res.get('historyId')}")

if __name__ == '__main__':
    start_watch()