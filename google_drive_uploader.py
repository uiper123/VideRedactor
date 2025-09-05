import base64
import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from config import GOOGLE_OAUTH_TOKEN_BASE64, TOKEN_PICKLE_FILE

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_gdrive_service():
    creds = None
    if os.path.exists(TOKEN_PICKLE_FILE):
        with open(TOKEN_PICKLE_FILE, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if GOOGLE_OAUTH_TOKEN_BASE64:
                token_data = base64.b64decode(GOOGLE_OAUTH_TOKEN_BASE64)
                with open(TOKEN_PICKLE_FILE, 'wb') as token:
                    token.write(token_data)
                with open(TOKEN_PICKLE_FILE, 'rb') as token:
                    creds = pickle.load(token)
            else:
                # This part should not be reached if the token is in .env
                # It's a fallback to the old flow.
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)

        with open(TOKEN_PICKLE_FILE, 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

def upload_to_drive(file_path, folder_name):
    service = get_gdrive_service()

    # Check if folder exists, create if not
    folder_id = None
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    if not response.get('files'):
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        folder_id = folder.get('id')
    else:
        folder_id = response.get('files')[0].get('id')

    # Upload the file
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    print(f"Uploading {os.path.basename(file_path)} to Google Drive...")
    file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    file_id = file.get('id')
    print(f"File ID: {file_id}")

    # Set permissions to anyone with the link
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    service.permissions().create(fileId=file_id, body=permission).execute()

    return file.get('webViewLink')

if __name__ == '__main__':
    # Example usage:
    # Create a dummy file to upload
    with open("test_upload.txt", "w") as f:
        f.write("This is a test file.")
    upload_to_drive("test_upload.txt", "Test Folder")
    os.remove("test_upload.txt")
