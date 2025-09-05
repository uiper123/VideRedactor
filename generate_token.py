# generate_token.py
import os.path
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# Укажите необходимые права доступа. ыв
# Для загрузки на диск достаточно 'https://www.googleapis.com/auth/drive'
SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_PICKLE_FILE = 'token.pickle'

def get_credentials():
    creds = None
    # Файл token.pickle хранит токены доступа и обновления пользователя.
    if os.path.exists(TOKEN_PICKLE_FILE):
        with open(TOKEN_PICKLE_FILE, 'rb') as token:
            creds = pickle.load(token)

    # Если нет действительных учетных данных, позволяем пользователю войти в систему.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Сохраняем учетные данные для следующего запуска
        with open(TOKEN_PICKLE_FILE, 'wb') as token:
            pickle.dump(creds, token)
    
    return creds

if __name__ == '__main__':
    print("Запускаем процесс аутентификации...")
    credentials = get_credentials()
    print("Аутентификация прошла успешно!")
    print(f"Файл '{TOKEN_PICKLE_FILE}' создан/обновлен.")
