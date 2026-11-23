# Colorful code and structured data

AiMate highlights fenced code in chat replies and your messages, structured
JSON/YAML or fenced code in My Diary, and JSON in reviewed action previews/results.
Colors follow Navy, Beige and Alienware Black/Blue themes.

Use a language after the opening fence, for example:

````text
```yaml
name: AiMate
ready: true
```
```json
{"name": "AiMate", "ready": true}
```
```python
print("AiMate")
```
```powershell
Write-Host "AiMate"
```
````

Common languages include JSON, YAML, Python, JavaScript, TypeScript, PowerShell,
shell, SQL, HTML/XML, CSS, C/C++ and Java. Unlabelled valid JSON and simple
multiline YAML are detected conservatively.

Text formatting is visual only. Copy code keeps the original text and whitespace.
Unknown languages remain readable, incomplete streaming code stays safe, and code
over 50,000 characters stays plain to keep rendering responsive.

highlight.js is bundled locally with its license and verified npm integrity.
Code is not sent to a highlighting service. Raw HTML and remote Markdown images
remain disabled. The same static renderer is packaged into the Pages interface.

For the new laptop, the updated restore tool in `AiMate-Migration` automatically
applies the verified `repo-updates` files after restoring your encrypted backup.
Saved data and credentials are left intact. Alternatively, take a fresh encrypted backup.
