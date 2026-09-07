Migration helpers for attendence_system

add_student_columns.py
- Adds `Added_by` (VARCHAR) and `Created_at` (DATETIME) to `Student_reg` table if missing.
- Intended for MySQL (uses INFORMATION_SCHEMA). Run with the project's virtualenv active.

Usage:

```bash
# activate venv on Windows (PowerShell)
& .\.venv\Scripts\Activate.ps1
python scripts/add_student_columns.py
```
