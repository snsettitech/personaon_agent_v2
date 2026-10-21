
import sys
import subprocess
import importlib.util

def setup_youtube_auth():
    """
    Runs yt-dlp to perform OAuth2 authentication.
    This allows the backend to use the cached credentials.
    """
    print("================================================================")
    print("YouTube OAuth2 Setup")
    print("================================================================")
    print("This script will authorize 'yt-dlp' to access YouTube as you.")
    print("This is required to bypass bot detection on your IP.")
    print("")
    print("INSTRUCTIONS:")
    print("1. A code will appear below (e.g., ABCD-1234).")
    print("2. Go to https://www.google.com/device in your browser.")
    print("3. Enter the code.")
    print("4. Authorize the application.")
    print("================================================================")

    # Check if yt-dlp is installed
    if importlib.util.find_spec("yt_dlp") is None:
        print("Error: yt-dlp is not installed. Run 'pip install yt-dlp'.")
        return

    # Run yt-dlp with oauth2 to trigger the flow
    # We use a dummy command (simulate) just to trigger auth
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--username", "oauth2",
        "--password", "",
        "--simulate",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rick Roll as test video
    ]

    try:
        subprocess.run(cmd, check=True)
        print("\nSUCCESS! OAuth2 tokens have been cached.")
        print("You can now restart your backend and import videos.")
    except subprocess.CalledProcessError as e:
        print(f"\nError during authentication: {e}")
        print("Please try running manually: yt-dlp --username oauth2 --password '' --simulate https://www.youtube.com/watch?v=dQw4w9WgXcQ")

if __name__ == "__main__":
    setup_youtube_auth()
