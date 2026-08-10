# Jarvis Personal AI Assistant - Testing Plan

## Test Strategy & Verification Suite

The testing strategy covers automated unit testing, intent classification verification, safety blocklist validation, and manual GUI walkthroughs.

---

## 1. Automated Unit Tests (`jarvis_assistant/tests/test_jarvis.py`)

Run the test suite via terminal:
```cmd
python -m unittest jarvis_assistant/tests/test_jarvis.py
```

### Covered Test Cases:
- `test_safety_checker_protected_paths`: Verifies that `C:\Windows` and `System32` are flagged as protected.
- `test_safety_checker_dangerous_commands`: Validates pattern blocking for `format c:` and system path `del` commands.
- `test_memory_manager`: Ensures message insertion, retrieval, and preference setting work in SQLite.
- `test_coordinator_routing`: Tests intent classification across Optimization, Windows Control, File Agent, and Browser Intelligence.
- `test_file_agent_search`: Verifies file search matching logic.
- `test_file_agent_safe_delete_protection`: Confirms that attempts to delete system paths are rejected.

---

## 2. Manual Verification Checklist

1. **System Performance Dashboard**:
   - Open GUI (`python main.py`).
   - Click **Dashboard** on the sidebar.
   - Verify live CPU %, RAM GB/%, and Storage C: progress bars update automatically.
   - Click **Clean Temp Cache** and check output.

2. **Windows Control**:
   - In Assistant Chat, type `Open Notepad`. Verify Notepad opens.
   - Type `Mute volume`. Verify volume toggles.
   - Type `Lock PC` or test scheduled shutdown.

3. **Browser Intelligence**:
   - Type `Search browsing history for "Python"`.
   - Verify history entries appear in markdown tables.
   - Type `Show browser RAM usage`. Verify active browser processes are listed with RAM consumption.

4. **Safety Confirmation Popups**:
   - Type `Delete file C:\Users\lohit\Downloads\test.txt`.
   - Verify safety confirmation modal appears asking for explicit user approval.
