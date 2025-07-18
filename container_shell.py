# import subprocess
# import shutil


# def run_exec_shell(container_id: str):
#     """
#     Launches an interactive shell (`/bin/bash` or `/bin/sh`) inside the specified Docker container
#     using the first available terminal emulator.
#     """
#     shells = ["/bin/bash", "/bin/sh"]
#     terminal_commands = []

#     for shell in shells:
#         docker_cmd = f"docker exec -it {container_id} {shell}"
#         terminal_commands.extend(
#             [
#                 ("kitty", ["kitty", "sh", "-c", docker_cmd]),
#                 ("gnome-terminal", ["gnome-terminal", "--", "sh", "-c", docker_cmd]),
#                 ("xterm", ["xterm", "-e", docker_cmd]),
#                 ("alacritty", ["alacritty", "-e", "sh", "-c", docker_cmd]),
#                 ("konsole", ["konsole", "-e", "sh", "-c", docker_cmd]),
#             ]
#         )

#     for name, cmd in terminal_commands:
#         if shutil.which(cmd[0]):
#             try:
#                 subprocess.Popen(cmd)
#                 print(f"✅ Opened interactive shell in terminal: {name}")
#                 return
#             except Exception as e:
#                 print(f"❌ Failed with {name}: {e}")

#     print("❌ No compatible terminal found or all shell attempts failed.")
