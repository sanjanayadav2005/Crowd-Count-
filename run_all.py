import subprocess
import time
import sys


def launch_service(label, command):
    """Launch a service in a new Windows terminal window."""
    print(f"[INFO] Starting {label}...")

    try:
        subprocess.Popen(
            f'start cmd /k "{command}"',
            shell=True
        )
        print(f"[SUCCESS] {label} launched")

    except Exception as error:
        print(f"[ERROR] Failed to start {label}: {error}")


def main():
    print("\n🚀 Launching People Counting System...\n")

    services = [
        ("Detection", "python module2_people_detection_counting.py"),
        ("Dashboard", "streamlit run module3_dashboard_visualization.py"),
        ("Admin Panel", "streamlit run module4_admin_panel_settings.py"),
    ]

    for i, (label, command) in enumerate(services):
        launch_service(label, command)

        if i < len(services) - 1:
            time.sleep(2)

    print("\n✅ All services launched successfully!")
    print("👉 Close individual terminals to stop services.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Launcher stopped by user.")
        sys.exit(0)
    except Exception as error:
        print(f"\n[CRITICAL ERROR] {error}")