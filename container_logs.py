import subprocess
import shutil
import json


def show_logs(container_id: str, tail: int = 100):
    def is_running(cid: str) -> bool:
        try:
            out = subprocess.check_output(["docker", "inspect", cid])
            return json.loads(out)[0]["State"]["Running"]
        except:
            return False

    follow = is_running(container_id)
    # Use bash -i -c to keep shell open after logs
    log_cmd = f"docker logs {'-f' if follow else ''} --tail {tail} {container_id}; echo ''; echo 'Press any key to exit...'; read -n 1"

    wrapped_cmd = f'bash -i -c "{log_cmd}"'

    terminal_commands = [
        ["kitty", "sh", "-c", wrapped_cmd],
        ["gnome-terminal", "--", "bash", "-i", "-c", log_cmd],
        ["xterm", "-hold", "-e", log_cmd],
        ["alacritty", "-e", "bash", "-i", "-c", log_cmd],
        ["konsole", "-e", "bash", "-i", "-c", log_cmd],
    ]

    for cmd in terminal_commands:
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd)
                return
            except Exception as e:
                print(f"❌ Failed to launch logs with {cmd[0]}: {e}")

    print("❌ No compatible terminal found to show logs.")
