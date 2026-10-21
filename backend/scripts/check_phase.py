import re
import os
import subprocess

def get_existing_tags():
    try:
        tags = subprocess.check_output(["git", "tag"]).decode("utf-8").split("\n")
        return [t.strip() for t in tags if t.strip()]
    except Exception as e:
        print(f"Error fetching tags: {e}")
        return []

def check_roadmap():
    roadmap_path = "ROADMAP.md"
    if not os.path.exists(roadmap_path):
        print(f"Error: {roadmap_path} not found.")
        return

    with open(roadmap_path, encoding="utf-8") as f:
        content = f.read()

    # Pattern to find Phase sections and their status
    # Group 1: Phase Number, Group 2: Full Title, Group 3: Status
    # We look for ## ... Phase X ... followed by **Status: ...**
    pattern = r"## (.*?Phase (\d+).*?)\n\*\*Status: (.*?)\*\*"
    matches = re.findall(pattern, content, re.IGNORECASE)

    existing_tags = get_existing_tags()

    new_phase_detected = False
    phase_tag = ""
    phase_name = ""
    phase_notes = ""

    for full_title, phase_num, status in matches:
        status = status.strip()
        phase_num = phase_num.strip()
        full_title = full_title.strip()

        if "Completed" in status:
            tag = f"v{phase_num}.0.0-phase{phase_num}"

            if tag not in existing_tags:
                print(f"Detected new completed phase: {full_title}")
                new_phase_detected = True
                phase_tag = tag
                phase_name = full_title

                # Extract notes (everything until the next header or end of file)
                # This is a bit simplified, but gets the bullet points
                phase_start = content.find(full_title)
                next_section = content.find("---", phase_start)
                if next_section == -1:
                    next_section = len(content)

                phase_notes = content[phase_start:next_section].strip()
                # Clean up the notes a bit
                phase_notes = phase_notes.replace(f"{full_title}\n**Status: {status}**", "").strip()
                break # Only process one new phase at a time to be safe

    # Output for GitHub Actions
    if new_phase_detected:
        # Using environment files for GHA
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("NEW_PHASE_DETECTED=true\n")
                f.write(f"PHASE_TAG={phase_tag}\n")
                f.write(f"PHASE_NAME={phase_name}\n")
                # Notes might have newlines, so we use a multiline string format for GHA output
                f.write(f"PHASE_NOTES<<EOF\n{phase_notes}\nEOF\n")
        else:
            # Local testing output
            print("NEW_PHASE_DETECTED=true")
            print(f"PHASE_TAG={phase_tag}")
            print(f"PHASE_NAME={phase_name}")
            print(f"PHASE_NOTES={phase_notes}")
    else:
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("NEW_PHASE_DETECTED=false\n")
        else:
            print("No new completed phases detected.")

if __name__ == "__main__":
    check_roadmap()
