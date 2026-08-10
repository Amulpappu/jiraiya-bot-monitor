import sys
import os
import argparse

# Add parent directory to sys.path
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from jarvis_assistant.core.coordinator import CoordinatorAgent

def run_cli_mode(coordinator: CoordinatorAgent):
    """Interactive CLI Mode for terminal usage or environments without PySide6."""
    print("=" * 60)
    print("🤖 Jarvis Personal AI Assistant (Windows) - CLI Mode")
    print("Type your command or prompt. Type 'exit' or 'quit' to stop.")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("You > ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            if not user_input:
                continue

            response_md, agent_name, requires_confirm, details = coordinator.process_request(user_input)
            
            if requires_confirm:
                print(f"\n⚠️ {response_md}")
                choice = input("Do you confirm this action? (y/n): ").strip().lower()
                if choice in ["y", "yes"]:
                    response_md, agent_name, _, _ = coordinator.process_request(user_input, confirm_token=True)
                else:
                    response_md = "Operation cancelled by user."

            print(f"\nJarvis ({agent_name}) >\n{response_md}\n")
            print("-" * 60)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting Jarvis.")
            break

def run_gui_mode():
    """Launches PySide6 GUI Application."""
    try:
        from PySide6.QtWidgets import QApplication
        from jarvis_assistant.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName("Jarvis Personal AI Assistant")
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except ImportError:
        print("PySide6 is not installed. Falling back to CLI mode...")
        coordinator = CoordinatorAgent()
        run_cli_mode(coordinator)

def main():
    parser = argparse.ArgumentParser(description="Jarvis Personal AI Assistant for Windows")
    parser.add_argument("--cli", action="store_true", help="Force CLI interactive mode instead of PySide6 GUI")
    parser.add_argument("--cmd", type=str, help="Execute a single command directly and exit")
    args = parser.parse_args()

    coordinator = CoordinatorAgent()

    if args.cmd:
        res, agent_used, _, _ = coordinator.process_request(args.cmd, confirm_token=True)
        print(f"\n[Jarvis - {agent_used}]\n{res}\n")
        return

    if args.cli:
        run_cli_mode(coordinator)
    else:
        run_gui_mode()

if __name__ == "__main__":
    main()
