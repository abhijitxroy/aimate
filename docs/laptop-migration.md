# Move AiMate to another laptop

## Old laptop

1. Finish the current request. Stop the AiMate server with Ctrl+C in its terminal.
2. Open PowerShell in your AiMate app folder.
3. Run `.\backup.ps1`.
4. Enter and confirm a new backup password of at least 12 characters. Keep it in your password manager; it cannot be recovered.
5. Wait for **Encrypted backup verified and saved** and **Full restore check: PASS**. The complete **AiMate-Migration** folder is saved at the top level of your work OneDrive.
6. Wait for OneDrive to finish syncing. Open OneDrive **in your browser** and confirm the `.aimate-backup`, `Restore-AiMate.ps1`, `portable_backup.py`, `device_key.py` and `START-HERE.md` files are present. Download the backup once from the browser to confirm it is available independently of this laptop. Saving locally does not prove cloud sync.
7. Keep your backup password somewhere you can access after surrendering this laptop, such as your password manager on your phone. Do not keep the only copy on the old laptop.

## New laptop

1. Install Python **3.11 or newer**, including the Windows Python launcher (`py`).
2. Sign in to the **same work OneDrive account**. Download the complete **AiMate-Migration** folder or sync it and choose **Always keep on this device**. Open PowerShell inside that folder.
3. Run `.\Restore-AiMate.ps1`.
4. Enter your backup password. The tool restores to `C:\Users\<your-user>\AiMate` and installs the app dependencies.
5. Run:

   ```powershell
   cd "$env:USERPROFILE\AiMate"
   .\run_aimate.ps1
   ```

6. Open **http://127.0.0.1:8765**. Check saved chats, My Diary, To-do, Usage, and Connections. Use **Save & check** for each connection to verify access from the new laptop.

If PowerShell blocks these scripts, and your company's policy permits it, use `powershell -ExecutionPolicy Bypass -File .\backup.ps1` or `powershell -ExecutionPolicy Bypass -File .\Restore-AiMate.ps1`. This applies only to that process.

To choose another new folder: `.\Restore-AiMate.ps1 -Destination 'D:\AiMate'`.
With multiple backups: `.\Restore-AiMate.ps1 -Backup '.\AiMate-20261123-120000.aimate-backup'`.
Existing destination folders are never overwritten.

## What is preserved

- Current app code, including local uncommitted changes and `.env` if present.
- Saved chats, projects/groups, icons, archives, references, attachments, My Diary, tasks, feedback, usage and action records.
- Connection settings, encrypted service tokens, vault entries, workspace passwords, authenticator enrollment and user workspaces.
- Saved ChatGPT accounts, protected again for the new Windows account. Expired/revoked provider sessions may still require signing in again.

Windows encryption is re-created on the new device. You do not need the old laptop's Windows password to restore.
Dependencies are installed fresh; the old `.venv` and Git history are excluded.

Private/session-only chats, browser theme/sidebar preferences, unsent drafts and files outside the app/data folders are not included. Machine-level proxy, certificates, VPN and environment overrides must be configured separately; the tool lists relevant environment variable **names**, never their secret values. Restored data is always inside the new app's `.data` folder. If `APP_DATA_DIR` is set on the new laptop, point it there or unset it before starting.

Intel Jira/Jenkins still require an approved laptop and Intel network/VPN access. Keep the encrypted backup private; do not add it to GitHub or GitHub Pages. You can surrender the old laptop after the full restore check passes, you have confirmed the files exist in OneDrive online, and you have retained the backup password separately. If your work OneDrive account will also be closed, this location will no longer be accessible; arrange an approved transfer before that happens.

If dependency installation fails after restore, your data remains restored. From the new AiMate folder run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`127.0.0.1` always refers to the laptop where the app is running; it is not a shared remote address.
