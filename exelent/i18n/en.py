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
    "py_syntax_error": (
        "There is a syntax error in {file}, line {line}: {detail}. "
        "A program written like this will not run — fix it and try again."
    ),
    "target_syntax_error": (
        "There is an error in {file}, line {line}: {detail}. The code does not compile on the "
        "target Python {version} — the built EXE would be missing this module and fail at "
        "startup. Fix it and try again."
    ),
    "txt_no_code": (
        "There is no code to run in {file} — only chat-window wrapping or an empty block was "
        "left. Paste the program and try again."
    ),
    "txt_multiple_blocks": (
        "{file} contains {count} code blocks (lines {ranges}). They were joined in order — "
        "if any block is an alternative version rather than a continuation, keep only "
        "the one you need."
    ),
    "txt_collision": (
        "Turning {file} into code would produce {target}, but that file already exists in the "
        "project. Keep only one version and try again."
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
    "frozen_path_pattern": (
        "Your code uses {pattern}, which points to the unpacking folder after packaging — "
        "not where the EXE actually sits. Relative file paths built from it may read or write "
        "to unexpected places. EXElent does not rewrite your code; check these paths yourself "
        "before sharing the EXE."
    ),
    "size_estimate": "The finished program will take about {low}–{high} MB. Largest: {packages}.",
    "size_estimate_large": (
        "The finished program will take about {low}–{high} MB and will take longer than usual "
        "to build. Largest: {packages}."
    ),
    # dependency manifests
    "requirements_missing": (
        "The requirements list points to {file}, which is not there — the list of extra "
        "packages may be incomplete."
    ),
    "requirements_cycle": (
        "The requirements files refer to each other in a loop (through {file}); the repeat "
        "was skipped."
    ),
    "pyproject_unreadable": (
        "{file} could not be read, so its declared packages were skipped — they will be "
        "detected from the code instead."
    ),
    "pyproject_dynamic_deps": (
        "{file} declares its packages dynamically, so they were detected from the code instead."
    ),
    "dependency_not_declared": (
        "Your code uses the {package} library, which is missing from the requirements list — "
        "it was included so the program works."
    ),
    "module_name_collision": (
        'Two files share the module name "{module}" in different folders ({files}). '
        "One would hide the other at runtime — rename one or keep only the one you need."
    ),
    "requirements_unsupported_option": (
        "The option {option} in {file} is not supported — it was skipped. "
        "The list of packages may be incomplete."
    ),
    "version_mismatch": (
        "The library {package} was installed as version {installed}, but {declared} was "
        "declared. Make sure the program works with this version."
    ),
    "requirements_invalid_spec": (
        'The requirement "{spec}" could not be understood and was skipped — '
        "the list of packages may be incomplete."
    ),
    "poetry_version_fallback": (
        'The Poetry version constraint "{constraint}" could not be fully interpreted — '
        "only a minimum version was used. Check that the installed version is correct."
    ),
    "requires_python_mismatch": (
        'The project declares requires-python = "{declared}", which does not include '
        "the target Python {target}. The build may still work, but the program was not "
        "designed for this version."
    ),
    "asset_collides_with_generated": (
        "The file {file} has the same name as a file the build creates ({generated}). "
        "Rename it to avoid the conflict."
    ),
    "asset_path_collision": (
        "Two files end up at the same path in the finished program: {file_a} and {file_b}. "
        "On Windows, file names that differ only in capitalisation are the same file — "
        "rename one."
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
        "The finished file {name} disappeared during the build. Check the output folder "
        "and your security software's protection history to find the cause."
    ),
    "fence_label_removed": (
        "The first line of {file} was a stray label from a chat window — I removed it "
        "so the program could be built."
    ),
    "module_dropped": (
        "{file} contains an error that stopped it from loading, so it was left out of the "
        "finished program. Fix that file and build again."
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
    "required_package_failed": (
        "A required library could not be installed: {packages}. The EXE was not built, because "
        "it would crash on the person you give it to. Check the library name and your internet "
        "connection, then try again."
    ),
    "requirements_conflict": (
        "The required libraries have conflicting version requirements that cannot be satisfied "
        "together. The EXE was not built — the environment would be inconsistent. Reconcile the "
        "versions in your requirements (e.g. in requirements.txt) and try again."
    ),
    "source_changed_after_analysis": (
        "Source files changed after the analysis ({files}). "
        "The EXE was not built — the finished program could differ from what you accepted. "
        "Try again so EXElent analyses the current code."
    ),
    "validation_failed": (
        "The code could not be checked with the target Python {version}, so the build was "
        "stopped — this was a failure of the check itself, not a confirmation that the code is "
        "fine. Try again; if it keeps happening, please report it. Details: {detail}"
    ),
    "antivirus_blocked": (
        "Writing the file was blocked. Check your antivirus protection history "
        "and the alert details before trying again."
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
    "publish_incomplete": (
        "The finished {name} could not be copied to the destination folder in full. Nothing "
        "was overwritten — your previous version is untouched. Try building again."
    ),
    "publish_failed": (
        "The finished program could not be saved to {path}. Nothing was overwritten — your "
        "previous version is untouched. Check the folder and try again."
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
    "file_read_error": "Cannot read {file} — skipping it.",
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
    "download_checking": "checking size…",
    "download_size": "{count} packages — about {size} to download",
    "download_nothing": "Everything is already downloaded — the build starts right away",
    "download_transfer": "Transfer: {count} missing packages, about {size}",
    "download_transfer_cached": "Package transfer: 0 B — every archive is cached",
    "download_transfer_unknown": "Transfer: could not be determined without guessing",
    "download_environment_min": (
        "Environment: at least {size} (compressed archives; larger after extraction)"
    ),
    "download_environment_unknown": "Environment: size unknown",
    "download_artifact_estimate": "Finished program: estimated {low}–{high} MB",
    "download_artifact_unknown": "Finished program: no reliable measurement for these packages",
    "download_component_uv_cached": "uv is on disk",
    "download_component_uv_missing": "uv must be downloaded",
    "download_component_python_cached": "Python 3.12 is on disk",
    "download_component_python_missing": "Python 3.12 must be downloaded",
    "download_component_tools": "build tools included",
    "download_components": "Components: {components}",
    "dialog_download_title": "Required extras",
    "dialog_download_body": (
        "Building this program needs {count} packages — about {size}. "
        "This happens once; later builds will be faster."
    ),
    "dialog_download_body_estimate": (
        "Building this program may require downloading uv, Python, build tools, and "
        "extras. The transfer size could not be checked. The finished program is "
        "estimated at {low}–{high} MB; this range is not the download size. "
        "This happens once; later builds will be faster."
    ),
    "dialog_download_body_unknown": (
        "Building this program may require downloading uv, Python, and build tools. "
        "The transfer size could not be determined reliably."
    ),
    "dialog_download_ok": "Download and build",
    "dialog_download_cancel": "Cancel",
    "dialog_download_dont_ask": "Do not ask again",
    "settings_title": "Settings",
    "settings_ask_download": "Ask before downloading extras",
    "settings_language": "Language",
    "settings_language_system": "Same as system",
    # screen 1 - picking the folder
    "drop_headline": "Drag a folder or a file with your code here",
    "drop_analyzing": "Analysing your code…",
    "drop_browse": "Choose…",
    "drop_recent": "Recent",
    # screen 2 - what I understood
    "review_headline": "Here is what I understood",
    "review_entry": "Main program",
    "review_kind": "Kind of program",
    "review_name": "File name",
    "review_icon": "Icon",
    "review_pick_icon": "choose",
    "review_icon_filter": "Images (*.png *.jpg *.jpeg *.ico)",
    "review_deps_title": "Preparation and finished program sizes",
    "review_extra_modules": "Missing a module? Add it here",
    "review_extra_modules_placeholder": "e.g. my_plugin, package.submodule — separate with commas",
    "review_extra_modules_help": (
        "Added names become hidden imports. EXElent will try to map their first component "
        "to a package, but private plug-ins may need their own manifest."
    ),
    "single_file_extra": "Also including: {files}",
    "review_mode": "Result layout",
    "review_target": "Target Python",
    "review_destination": "Full publication location",
    "review_destination_change": "Change publication location…",
    "review_destination_pick": "Choose publication location",
    "review_scope_title": "Scope accepted for the build",
    "review_scope_source": "Input: {path}",
    "review_scope_summary": (
        "Sources: {sources} · TXT conversions: {conversions} · resources: {resources} · "
        "project dependencies: {dependencies}"
    ),
    "review_preview_button": "Show original, result, and diff",
    "review_preview_title": "Conversion preview — {file}",
    "review_preview_original": "Original TXT",
    "review_preview_result": "Python result",
    "review_preview_diff": "Diff",
    "review_preview_unavailable": "The original file can no longer be read.",
    "review_recommended_suffix": "(recommended)",
    "review_restore": "restore recommended",
    "review_trust_warning": (
        "Only build code and dependencies from a trusted source. Building may run "
        "code during package installation."
    ),
    "review_build": "Create EXE",
    "review_back": "← Back",
    "kind_windowed": "A program in a window",
    "kind_console": "A console program",
    "mode_onefile": "A single EXE file",
    "mode_onedir": "A folder with the program",
    "onefile_no_resource_guarantee": (
        "A single EXE file: bundled files are unpacked into a temporary folder, so "
        "reading a resource by a relative path (e.g. open('config.json')) may fail. If "
        "the program reads files that sit next to it, choose “A folder with the "
        "program”. Files the program writes land next to the EXE and stay there."
    ),
    # screen 3 - building and result
    "build_cancel": "Stop",
    "build_cancelling": "Stopping…",
    "build_open_folder": "Show in folder",
    "build_run": "Run",
    "build_save_report": "Save report",
    "build_report_filter": "Text file (*.txt)",
    "build_report_github": "Report on GitHub",
    "build_again": "Make another program",
    "build_back_to_review": "← Back to settings",
    "build_show_log": "Show details",
    "build_hide_log": "Hide details",
    "build_success": "Created {name} — {size}. Its launch has not been verified.",
    "build_success_warnings": (
        "Created {name} with warnings — {size}. Its launch has not been verified."
    ),
    "build_success_verified": "Created {name} and verified its launch — {size}.",
    "build_success_verified_warnings": (
        "Created {name} with warnings and verified its launch — {size}."
    ),
    "build_launch_started": (
        "The system started the program; EXElent has not verified its result."
    ),
    "build_run_failed": "The program could not be started: {error}",
    "build_open_failed": "The result folder could not be opened: {error}",
    "build_failed_title": "It did not work",
    "build_failed_unknown": (
        "I do not recognise this error. Save a report or send it in — it will help fix EXElent."
    ),
    "antivirus_note": (
        "If your antivirus raises an alert, check the program's source and the alert details. "
        "EXElent cannot confirm that the program is safe or that the alert is a false positive."
    ),
}
