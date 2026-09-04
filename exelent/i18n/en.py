"""English sentences for the core's codes.

Same keys as `pl.py` — a test keeps the two catalogs in step. Written for
someone who does not use a terminal: what happened, and what to do about it.
"""

CATALOG: dict[str, str] = {
    # analysis
    "no_python_found": (
        "I cannot find a Python program in {dir}. "
        "Check whether the folder you picked contains the code files."
    ),
    "other_language": (
        "This code is written in a language other than Python ({suffix} files). "
        "EXElent only supports Python for now."
    ),
    "multiple_entry_points": (
        "There is more than one program here: {first} and {second}. Pick the one to build."
    ),
    "scan_truncated": (
        "This folder is very large ({files} files). Check that you picked the right place."
    ),
    "single_file_too_many": (
        "This file pulls in a great many other files from the same folder. "
        "Building just the file you picked — if that is not enough, point me at the whole folder."
    ),
    "txt_syntax_error": (
        "There is an error in {file}, line {line}: {detail}. Fix it and try again."
    ),
    "no_entry_point": (
        "I cannot tell which file starts your program. Point me at the one you normally run."
    ),
    # warnings about the code
    "server_app": (
        "This is a server ({framework}). Once started, the window will look idle "
        "— the program is waiting for connections."
    ),
    "external_tool": (
        "Your program uses an external tool ({tool}) that cannot be packed into an EXE. "
        "Whoever runs the program needs it installed."
    ),
    "secrets_in_code": (
        "I found something in the code that looks like an access key. It can be read out "
        "of the finished EXE — do not share that file publicly."
    ),
    "dynamic_import_unresolved": (
        "Your program loads libraries while it runs. One of them may not make it into the EXE."
    ),
    "heavy_packages": (
        "This program uses large libraries ({packages}). The EXE may be several hundred "
        "megabytes, and building will take longer."
    ),
    # environment
    "no_network": (
        "No internet connection. The first build needs to download tools — connect and try again."
    ),
    "low_disk_space": "Not enough disk space: {free_gb} GB free, about {needed_gb} GB needed.",
    "uv_download_failed": (
        "The tools could not be downloaded. Check your internet connection and firewall settings."
    ),
    "env_setup_failed": (
        "The build environment could not be prepared. Check your internet connection and try again."
    ),
    # build
    "build_cancelled": "Build cancelled.",
    "cancel_incomplete": (
        "The build was cancelled, but one process may still be running in the background. "
        "If the next build behaves oddly, restart your computer."
    ),
    "artifact_vanished": (
        "The finished file {name} disappeared during the build. This is usually antivirus "
        "software — add an exception and try again."
    ),
    "package_not_found": (
        "One of the required libraries could not be downloaded. "
        "Check that its name in the code is correct."
    ),
    "module_not_found": (
        "The library {module} is missing. Add it to the extras list or fix the import in your code."
    ),
    "packages_failed": (
        "These libraries could not be included: {packages}. The EXE will still be built, "
        "but it may not start on someone else's computer."
    ),
    "antivirus_blocked": (
        "Antivirus software blocked writing the file. "
        "Add the EXElent folder to its exceptions and try again."
    ),
    "cloud_file_unavailable": (
        "The file {file} is kept in the cloud and is not on this computer. Open it once in "
        "File Explorer, or tick “Always keep on this device”, and try again."
    ),
    "file_in_use": (
        "One of the files is currently in use by another program. Close it and try again."
    ),
    "dest_in_use": (
        "I cannot save the result in {path} — an earlier version of the program is in use "
        "right now. Close it and try again."
    ),
    "access_denied": (
        "Windows denied access to a file. Check that you have permission to that folder."
    ),
    "path_too_long": (
        "The path to the files is too long for Windows. Move the code folder closer to the "
        "drive root, for example to C:\\code."
    ),
    "ssl_proxy": (
        "The connection was intercepted by a firewall or proxy server. "
        "On a company network you may need help from an administrator."
    ),
    "disk_full": "The disk ran out of space during the build.",
    "recursion_limit": "The build hit a very complex code structure and stopped analysing it.",
    "script_failed": "The program that was built did not start correctly.",
    "encoding_problem": "One of the files uses an unusual character encoding.",
    "unexpected_error": (
        "Something went wrong and I cannot name it ({error}). "
        "Attach the report to your issue — with it this can be fixed."
    ),
    # progress phases
    "download_uv": "Downloading tools…",
    "install_python": "Preparing Python…",
    "create_env": "Creating the environment…",
    "install_packages": "Downloading extras…",
    "build_start": "Starting the build…",
    "analyze": "Analysing your code…",
    "hooks": "Preparing libraries…",
    "libraries": "Collecting files…",
    "package": "Packing into an EXE…",
    "collect": "Finishing…",
    "done": "Done!",
    "progress_bytes": "{done} of {total}",
    "progress_eta": "{eta} left",
    # screen 1 - picking the folder
    "drop_headline": "Drag a folder with your code here",
    "drop_browse": "Choose folder",
    "drop_recent": "Recent",
    # screen 2 - what I understood
    "review_headline": "Here is what I understood",
    "review_entry": "Main program",
    "review_kind": "Kind of program",
    "review_name": "File name",
    "review_icon": "Icon",
    "review_pick_icon": "choose",
    "review_icon_filter": "Images (*.png *.jpg *.jpeg *.ico)",
    "review_deps_title": "Add-ons needed — they will be downloaded automatically",
    "single_file_extra": "Also including: {files}",
    "review_mode": "Result layout",
    "review_recommended_suffix": "(recommended)",
    "review_restore": "restore recommended",
    "review_build": "Create EXE",
    "review_back": "← Back",
    "kind_windowed": "A program in a window",
    "kind_console": "A console program",
    "mode_onefile": "A single EXE file",
    "mode_onedir": "A folder with the program",
    # screen 3 - building and result
    "build_cancel": "Stop",
    "build_open_folder": "Show in folder",
    "build_run": "Run",
    "build_save_report": "Save report",
    "build_report_filter": "Text file (*.txt)",
    "build_report_github": "Report on GitHub",
    "build_again": "Make another program",
    "build_back_to_review": "← Back to settings",
    "build_show_log": "Show details",
    "build_hide_log": "Hide details",
    "build_success": "Done! {name} — {size}",
    "build_failed_title": "It did not work",
    "build_failed_unknown": (
        "I do not recognise this error. Save a report or send it in — it will help fix EXElent."
    ),
    "antivirus_note": (
        "If your antivirus flags this file as suspicious, it is a false alarm typical of "
        "programs built this way. You can add the file to its exceptions."
    ),
}
