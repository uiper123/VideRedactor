# encode_token.py
import base64

TOKEN_PICKLE_FILE = 'token.pickle'

with open(TOKEN_PICKLE_FILE, 'rb') as token_file:
    # Читаем бинарное содержимое файла
    binary_content = token_file.read()
    # Кодируем в Base64 и декодируем в строку UTF-8 для вывода
    base64_encoded = base64.b64encode(binary_content).decode('utf-8')

print("Ваш GOOGLE_OAUTH_TOKEN_BASE64:\n")
print(base64_encoded)
