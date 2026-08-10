# Jarvis Personal AI Assistant - Security Review & Safety Rules

## Security Architecture & Privacy Policy

Jarvis is built strictly for **local, personal use on Windows**. Privacy and safety are foundational to the application design.

### 1. Data Privacy & Local Processing
- **Zero Third-Party Cloud Transmissions**: All conversations, memory logs, and browser history queries are processed 100% locally on your machine.
- **SQLite Local Encrypted Memory**: History and user preferences are stored in local SQLite database `data/jarvis_memory.db`.
- **Incognito & Private Browsing Isolation**: Browser intelligence agents access local database files only for default user profiles; incognito data is never touched.

### 2. Safety Rules & Protected Path Boundaries
The `SafetyChecker` class enforces non-bypassable system rules:
- **Protected Paths**: Operations targeting `C:\Windows`, `C:\Windows\System32`, `C:\Program Files`, or `C:\Program Files (x86)` are blocked immediately.
- **Dangerous Command Blocklist**: Destructive commands (e.g. `format c:`, `rmdir /s /q c:\`, `del /f /s /q c:\windows`, registry deletions) trigger security exceptions.
- **Mandatory User Confirmation**: Deleting user files/folders, terminating process IDs, restarting the PC, or initiating Windows shutdowns require interactive user confirmation popups.

### 3. Risk Mitigation Table

| Action Category | Security Risk | Mitigation Strategy |
| --- | --- | --- |
| File Deletion | Data Loss | Refuses system path deletion; requires UI confirmation popup for user paths. |
| Process Termination | Unsaved Work Loss | Displays PID and process name before closing. |
| System Shutdown/Restart | Workflow Interruption | Schedules 1-minute delay with `shutdown /a` abort command capability. |
| Browsing History Search | Privacy Exposure | Uses local read-only copy of history SQLite database. |
