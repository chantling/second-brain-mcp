"""Fix the indentation issue in watcher.py H2 fix."""

filepath = r'D:\Programs\AI\!MCPServers!\!Second_Brain!\second-brain-mcp\watcher.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the broken section with properly indented version
old = '''        with self._recent_deletes_lock:
            for deleted_path, (deleted_filename, deleted_rel_path, delete_time) in list(
                self._recent_deletes.items()
            ):
            time_diff = current_time - delete_time
            is_filename_match = (
                deleted_filename == filename
            )  # Same filename = likely a move
            is_time_match = (
                time_diff < 2.0
            )  # Create must happen within 2 seconds of delete

            _log(
                f"[CREATE] Comparing: deleted_file={deleted_filename}, created_file={filename}, filename_match={is_filename_match}, time_diff={time_diff:.2f}s",
                "CREATE",
            )

                if is_filename_match and is_time_match:
                    matching_delete = (
                        deleted_path,
                        deleted_filename,
                        deleted_rel_path,
                        delete_time,
                    )
                    _log(
                        f"[CREATE] ✓ MOVE DETECTED: {deleted_rel_path} → {rel_path}",
                        "CREATE",
                    )
                    break'''

new = '''        with self._recent_deletes_lock:
            for deleted_path, (deleted_filename, deleted_rel_path, delete_time) in list(
                self._recent_deletes.items()
            ):
                time_diff = current_time - delete_time
                is_filename_match = (
                    deleted_filename == filename
                )  # Same filename = likely a move
                is_time_match = (
                    time_diff < 2.0
                )  # Create must happen within 2 seconds of delete

                _log(
                    f"[CREATE] Comparing: deleted_file={deleted_filename}, created_file={filename}, filename_match={is_filename_match}, time_diff={time_diff:.2f}s",
                    "CREATE",
                )

                if is_filename_match and is_time_match:
                    matching_delete = (
                        deleted_path,
                        deleted_filename,
                        deleted_rel_path,
                        delete_time,
                    )
                    _log(
                        f"[CREATE] ✓ MOVE DETECTED: {deleted_rel_path} → {rel_path}",
                        "CREATE",
                    )
                    break'''

if old in content:
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print('Fixed indentation in on_created _recent_deletes section')
else:
    print('ERROR: Could not find the broken section')
    # Debug: show what's around line 334
    lines = content.split('\n')
    for i in range(330, 365):
        print(f'{i+1}: {repr(lines[i])}')
