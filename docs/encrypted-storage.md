# Encrypted storage

Chats, tasks, My Diary, metadata and the search index use SQLCipher 4 encryption.
Configuration and vault values also retain their existing Fernet protection.
The database key is derived separately from the device key, protected by Windows
DPAPI for the current Windows account. On Linux the key file is owner-readable.

New workspaces are encrypted immediately. For an existing workspace:

1. Finish requests and stop all AiMate servers using the data directory.
2. Run `.\.venv\Scripts\python.exe tools/migrate_storage.py --application-stopped`.
3. Restart AiMate. Production refuses a legacy unencrypted database.

Migration verifies every table and search index before replacing the database.
Encrypted rollback copies remain in the data directory. Interrupted migrations
preserve the original and can be retried. Do not delete the protected key.

The generated workspace password is encrypted in `access-password.fernet`.
To display it in your private terminal, run
`.\.venv\Scripts\python.exe tools/show_workspace_password.py`.
An `APP_PASSWORD` environment override still takes precedence.

Portable backup/restore supports old backups, encrypts restored databases, and
protects the key for the new Windows account. Keep the backup password separately.
Use the updated migration kit, which includes the SQLCipher dependency.

Encryption protects copied files without their key. An unlocked application,
your Windows account, an administrator or malware running with your account
can access decrypted data. AI-shared content is sent to the selected provider.
Logs, exports and files you save outside the database need their own protection.
Vault unlock and automatic locking are a separate privacy feature.
