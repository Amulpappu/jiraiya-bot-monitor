import os
import shutil
from pathlib import Path
from jarvis_assistant.core.safety import SafetyChecker

class FileAgent:
    """
    Manages local file search, document reading (PDF, DOCX, TXT, MD),
    file organization, directory creation, copying/moving,
    and safe user file deletion with confirmation requirements.
    """

    def search_files(self, keyword: str, start_directory: str = None, limit: int = 15) -> str:
        """Searches for files matching keyword starting from user home or specified directory."""
        if not start_directory:
            start_directory = os.path.expanduser("~")

        clean_start = os.path.expandvars(start_directory)
        if not os.path.exists(clean_start):
            return f"Search directory does not exist: `{start_directory}`"

        matches = []
        kw_lower = keyword.lower()

        try:
            for root, dirs, files in os.walk(clean_start):
                # Exclude hidden or system directories
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["AppData", "node_modules", "venv", "$RECYCLE.BIN"]]
                for f in files:
                    if kw_lower in f.lower():
                        full_path = os.path.join(root, f)
                        matches.append(full_path)
                        if len(matches) >= limit:
                            break
                if len(matches) >= limit:
                    break
        except Exception as e:
            return f"Error during file search: {e}"

        if not matches:
            return f"No files found matching **\"{keyword}\"** under `{clean_start}`."

        result = f"### 🔍 Found {len(matches)} File(s) matching \"{keyword}\":\n\n"
        for m in matches:
            result += f"- [`{os.path.basename(m)}`](file:///{m.replace('\\', '/')}) (`{m}`)\n"

        return result

    def find_large_files(self, directory: str = None, min_size_mb: int = 100, limit: int = 10) -> str:
        """Finds files larger than min_size_mb."""
        if not directory:
            directory = os.path.expanduser("~\\Downloads")

        directory = os.path.expandvars(directory)
        if not os.path.exists(directory):
            return f"Directory not found: `{directory}`"

        large_files = []
        min_bytes = min_size_mb * 1024 * 1024

        try:
            for root, _, files in os.walk(directory):
                for f in files:
                    try:
                        fp = os.path.join(root, f)
                        sz = os.path.getsize(fp)
                        if sz >= min_bytes:
                            large_files.append((fp, sz))
                    except Exception:
                        continue
        except Exception as e:
            return f"Error searching large files: {e}"

        large_files.sort(key=lambda x: x[1], reverse=True)
        top_files = large_files[:limit]

        if not top_files:
            return f"No files larger than **{min_size_mb} MB** found in `{directory}`."

        result = f"### 📦 Files larger than {min_size_mb} MB in `{directory}`:\n\n"
        result += "| File Name | Size (MB) | Full Path |\n| --- | --- | --- |\n"
        for fp, sz in top_files:
            sz_mb = round(sz / (1024 * 1024), 2)
            bname = os.path.basename(fp)
            result += f"| `{bname}` | `{sz_mb} MB` | `{fp}` |\n"

        return result

    def read_document(self, file_path: str) -> str:
        """Reads content of TXT, MD, PDF, or DOCX files."""
        clean_path = os.path.expanduser(os.path.expandvars(file_path))
        if not os.path.exists(clean_path):
            return f"File does not exist: `{file_path}`"

        ext = os.path.splitext(clean_path)[1].lower()

        try:
            if ext in [".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml"]:
                with open(clean_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(8000) # Read up to 8k chars
                return f"### Document Snippet: `{os.path.basename(clean_path)}`\n\n```\n{content}\n```"

            elif ext == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(clean_path)
                    text = ""
                    for page in reader.pages[:5]: # first 5 pages
                        text += page.extract_text() or ""
                    return f"### PDF Extracted Text: `{os.path.basename(clean_path)}`\n\n{text[:4000]}"
                except ImportError:
                    return f"PDF reading requires `pypdf`. File exists at `{clean_path}`."

            elif ext == ".docx":
                try:
                    import docx
                    doc = docx.Document(clean_path)
                    text = "\n".join([p.text for p in doc.paragraphs if p.text])
                    return f"### DOCX Extracted Text: `{os.path.basename(clean_path)}`\n\n{text[:4000]}"
                except ImportError:
                    return f"DOCX reading requires `python-docx`. File exists at `{clean_path}`."

        except Exception as e:
            return f"Failed to read document: {e}"

        return f"Unsupported file extension '{ext}' for direct text extraction."

    def create_folder(self, folder_path: str) -> str:
        """Creates a directory at folder_path."""
        clean_path = os.path.expanduser(os.path.expandvars(folder_path))
        try:
            os.makedirs(clean_path, exist_ok=True)
            return f"Created folder successfully at: `{clean_path}`"
        except Exception as e:
            return f"Failed to create folder: {e}"

    def move_file(self, src: str, dst: str) -> str:
        """Moves a file or folder from src to dst."""
        clean_src = os.path.expanduser(os.path.expandvars(src))
        clean_dst = os.path.expanduser(os.path.expandvars(dst))

        if not os.path.exists(clean_src):
            return f"Source path does not exist: `{src}`"

        try:
            shutil.move(clean_src, clean_dst)
            return f"Moved `{os.path.basename(clean_src)}` to `{clean_dst}`"
        except Exception as e:
            return f"Failed to move file: {e}"

    def rename_file(self, src: str, new_name: str) -> str:
        """Renames a file or directory."""
        clean_src = os.path.expanduser(os.path.expandvars(src))
        if not os.path.exists(clean_src):
            return f"Target path does not exist: `{src}`"

        parent = os.path.dirname(clean_src)
        clean_dst = os.path.join(parent, new_name)

        try:
            os.rename(clean_src, clean_dst)
            return f"Renamed `{os.path.basename(clean_src)}` to `{new_name}`"
        except Exception as e:
            return f"Failed to rename target: {e}"

    def safe_delete(self, target_path: str, confirmed: bool = False) -> str:
        """
        Deletes a file or directory safely.
        Requires explicit confirmation.
        Refuses to delete protected Windows folders under any circumstances.
        """
        clean_path = os.path.expanduser(os.path.expandvars(target_path))
        
        if SafetyChecker.is_path_protected(clean_path):
            return f"❌ **SECURITY BLOCK**: Deletion of protected Windows path `{clean_path}` is strictly prohibited."

        if not os.path.exists(clean_path):
            return f"Target path does not exist: `{clean_path}`"

        if not confirmed:
            req, msg = SafetyChecker.requires_confirmation("delete_file" if os.path.isfile(clean_path) else "delete_folder", {"target": clean_path})
            return f"⚠️ **Confirmation Required**: Say 'Yes' or confirm in UI to delete `{clean_path}`."

        try:
            if os.path.isfile(clean_path) or os.path.islink(clean_path):
                os.remove(clean_path)
            else:
                shutil.rmtree(clean_path)
            return f"Deleted target successfully: `{clean_path}`"
        except Exception as e:
            return f"Failed to delete target: {e}"
