"""Tier 1.6 — the tool declarations given to the live model.

Pure data, kept out of `main.py` so the entry point is no longer dominated by a
700-line literal. The permission gate (`config/autonomy.json`) and the dispatcher
(`JarvisLive._execute_tool`) still have to agree with this list; `agent.tool_contract`
checks all three in CI.
"""

from __future__ import annotations


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens an application, or brings it to the front if it is already "
            "open. Use this whenever the user asks to open, launch, or start an "
            "app or program. If the app is already running this focuses the "
            "existing window instead of opening a duplicate — so it is always "
            "safe to call. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "forget",
        "description": (
            "The user's own data, under their own control. Use action='report' "
            "to list what is stored about the user and where. Use action='export' "
            "to write a zip of it. Use action='forget' ONLY when the user "
            "explicitly asks to be forgotten, to have everything erased, or to "
            "delete their data — it is irreversible, and it removes memories, "
            "the profile, the spend ledger, the voiceprint, crash bundles and "
            "(unless include_audit is false) the audit log. Never call "
            "action='forget' because the user is frustrated or because it might "
            "help: ask first."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "report (default), export, or forget",
                    "enum": ["report", "export", "forget"],
                },
                "path": {
                    "type": "STRING",
                    "description": "Where to write the export zip (export only)",
                },
                "include_audit": {
                    "type": "BOOLEAN",
                    "description": (
                        "forget only: also wipe the audit log. Defaults to true; "
                        "false keeps the record of the deletion."
                    ),
                },
                "include_voiceprints": {
                    "type": "BOOLEAN",
                    "description": (
                        "forget only: also delete the voiceprint. Defaults to "
                        "true."
                    ),
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_open_windows",
        "description": (
            "Lists the windows and apps currently open on the computer. Call "
            "this when the user refers to something already open — 'continue', "
            "'that window', 'the app I opened', 'the same page' — and BEFORE "
            "opening an app or website, so you can continue in the existing "
            "window instead of opening a duplicate."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "devices",
        "description": (
            "Talks to your other devices (phone, laptop, tablet...) registered in "
            "config/devices.json. action=list shows what is registered, "
            "action=status asks a device how it is, and action=run performs one "
            "capability (cmd) on a target. A capability the device does not "
            "declare is refused. Reaching other people (sms, call) always needs "
            "your confirmation, and the shell capability is always blocked. If it "
            "reports a failure, say so — never claim success."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | status | run"},
                "target": {"type": "STRING", "description": "Device name from the registry"},
                "cmd":    {"type": "STRING", "description": "Capability: info, notify, screenshot, ring, media, sms, call, lock, exec, wol"},
                "text":   {"type": "STRING", "description": "Message text, for notify/sms"},
                "number": {"type": "STRING", "description": "Phone number, for sms/call"},
                "command": {"type": "STRING", "description": "Command, for exec"}
            },
            "required": ["action"]
        }
    },
{
    "name": "web_search",
    "description": "Searches the web for any information.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":  {"type": "STRING", "description": "Search query"},
            "mode":   {"type": "STRING", "description": "search (default) or compare"},
            "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
            "aspect": {"type": "STRING", "description": "price | specs | reviews"}
        },
        "required": ["query"]
    }
},
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
    "name": "youtube_video",
    "description": (
        "Controls YouTube. Use for: playing videos, summarizing a video's content, "
        "getting video info, or showing trending videos."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "play | summarize | get_info | trending (default: play)"
            },
            "query":  {"type": "STRING", "description": "Search query for play action"},
            "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
            "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
            "url":    {"type": "STRING", "description": "Video URL for get_info action"},
        },
        "required": []
    }
    },{
    "name": "spotify_control",
    "description": "Play music on Spotify app using system control.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "play"},
            "query": {"type": "STRING", "description": "Song name"}
        },
        "required": ["action"]
    }
},
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {
                    "type": "STRING",
                    "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"
                },
                "text": {
                    "type": "STRING",
                    "description": "The question or instruction about the captured image"
                }
            },
            "required": ["text"]
        }
    },
    {
    "name": "computer_settings",
    "description": (
        "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
        "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
        "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
        "ALSO use for repeated actions: 'refresh 10 times', 'reload page 5 times' → action: reload_n, value: 10. "
        "Use for ANY single computer control command — even if repeated N times. "
        "NEVER route simple computer commands to agent_task."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "The action to perform (if known). For repeated reload: 'reload_n'"},
            "description": {"type": "STRING", "description": "Natural language description of what to do"},
            "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, number of times, etc."}
        },
        "required": []
    }
},
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. It reuses ONE persistent browser window "
            "across calls, so pass a URL to continue browsing in that same "
            "window instead of opening a new one. Use for: opening websites, "
            "searching the web, clicking elements, filling forms, scrolling, "
            "finding cheapest products, booking flights, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders. Use for: listing files, creating/deleting/moving/copying "
            "files, reading file contents, finding files by name or extension, checking disk usage, "
            "organizing the desktop, getting file info."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands by understanding natural language. "
            "Use when user wants to: find large files, check disk space, list processes, "
            "get system info, navigate folders, check network, find files by name, "
            "or do ANYTHING in the command line they don't know how to do themselves."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do. Example: 'find the 10 largest files on C drive'"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window so user can see. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": (
            "Controls the desktop. Use for: changing wallpaper, organizing desktop files, "
            "cleaning the desktop, listing desktop contents, or ANY other desktop-related task "
            "the user describes in natural language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language description of any desktop task"},
            },
            "required": ["action"]
        }
    },
    {
    "name": "code_helper",
    "description": (
        "Writes, edits, explains, runs, or self-builds code files. "
        "Use for ANY coding request: writing a script, fixing a file, "
        "editing existing code, running a file, or building and testing automatically."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
            "description": {"type": "STRING", "description": "What the code should do, or what change to make"},
            "language":    {"type": "STRING", "description": "Programming language (default: python)"},
            "output_path": {"type": "STRING", "description": "Where to save the file (full path or filename)"},
            "file_path":   {"type": "STRING", "description": "Path to existing file for edit / explain / run / build"},
            "code":        {"type": "STRING", "description": "Raw code string for explain"},
            "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
            "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
        },
        "required": ["action"]
    }
    },
    {
    "name": "dev_agent",
    "description": (
        "Builds complete multi-file projects from scratch. "
        "Plans structure, writes all files, installs dependencies, "
        "opens VSCode, runs the project, and fixes errors automatically. "
        "Use for any project larger than a single script."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description":  {"type": "STRING", "description": "What the project should do"},
            "language":     {"type": "STRING", "description": "Programming language (default: python)"},
            "project_name": {"type": "STRING", "description": "Optional project folder name"},
            "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
        },
        "required": ["description"]
    }
    },
    {
        "name": "business",
        "description": (
            "Business tools: calendar, GitHub, mood music, document scanner, "
            "meeting scheduler, code review, health tracker, expense tracker. "
            "Use when user says 'add event', 'log expense', 'review code', "
            "'what's my health today', 'scan document', 'schedule meeting', "
            "'add github repo', 'play mood music', 'business dashboard', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "calendar_add | calendar_today | calendar_list | calendar_delete | github_repos | github_add_repo | github_issues | github_add_issue | mood_music | scan_doc | meeting_add | meeting_list | code_review | health | water | break | expense_add | expense_summary | expense_list | dashboard"
                },
                "id": {"type": "STRING", "description": "Record id (e.g. to delete an event)"},
                "title": {"type": "STRING", "description": "Event/task/repo/issue title"},
                "date": {"type": "STRING", "description": "Date YYYY-MM-DD"},
                "time": {"type": "STRING", "description": "Time HH:MM"},
                "description": {"type": "STRING", "description": "Details"},
                "amount": {"type": "NUMBER", "description": "Expense amount"},
                "category": {"type": "STRING", "description": "Category (food, transport, tools, etc.)"},
                "name": {"type": "STRING", "description": "Name"},
                "url": {"type": "STRING", "description": "URL"},
                "path": {"type": "STRING", "description": "File path"},
                "code": {"type": "STRING", "description": "Code to review"},
                "language": {"type": "STRING", "description": "Programming language"},
                "mood": {"type": "STRING", "description": "Mood for music"},
                "attendees": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Meeting attendees"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "enterprise",
        "description": (
            "Enterprise tools: task automation, email drafting, news monitoring, "
            "stock/crypto tracking, client CRM. "
            "Use when user says 'create automation', 'draft an email to', 'send email', "
            "'track news about', 'add to watchlist', 'stock price', 'add client', "
            "'update client status', 'add deal', 'crm summary', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "automation_create | automation_list | automation_toggle | automation_run | email_draft | email_drafts | email_send | email_config | email_test | news_add | news_topics | news_check | news_alerts | watchlist_add | watchlist_list | stock_price | price_alerts | client_add | client_list | client_status | deal_add | deal_list | crm_summary"
                },
                "name": {"type": "STRING", "description": "Automation name / client name"},
                "title": {"type": "STRING", "description": "Title / subject / deal title"},
                "trigger": {"type": "STRING", "description": "Automation trigger description"},
                "actions": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Automation actions"},
                "to": {"type": "STRING", "description": "Email recipient"},
                "subject": {"type": "STRING", "description": "Email subject"},
                "body": {"type": "STRING", "description": "Email body / details"},
                "topic": {"type": "STRING", "description": "News topic"},
                "keywords": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "News keywords"},
                "symbol": {"type": "STRING", "description": "Stock/crypto symbol"},
                "alert_price": {"type": "NUMBER", "description": "Price alert threshold"},
                "company": {"type": "STRING", "description": "Client company"},
                "email": {"type": "STRING", "description": "Client email"},
                "app_password": {"type": "STRING", "description": "Gmail app password (16 chars) for email_config"},
                "phone": {"type": "STRING", "description": "Client phone"},
                "status": {"type": "STRING", "description": "Client/deal status"},
                "stage": {"type": "STRING", "description": "Deal stage"},
                "value": {"type": "NUMBER", "description": "Deal/client value"},
                "id": {"type": "STRING", "description": "Record id"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "life",
        "description": (
            "Personal life management: habits & streaks, focus/Pomodoro sessions, "
            "knowledge base (notes & links), meeting recording + summaries, "
            "daily routine alarms, and finance / net-worth tracking. "
            "Use when user says 'log my habit', 'start focus', 'save a note', "
            "'search my notes', 'start meeting recording', 'summarize this', "
            "'add a routine', 'log income', 'add invoice', 'net worth', "
            "'finance dashboard', 'life briefing', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "habit_add | habit_log | habits | habit_status | habits_at_risk | focus_start | focus_end | focus_stats | focus_report | note_add | note_search | notes | note_delete | link_add | links | meeting_start | meeting_stop | meeting_save | meeting_summarize | recordings | routine_add | routines | routine_remove | routines_due | income_add | invoice_add | invoice_status | asset_add | liability_add | net_worth | finance_summary | finance_dashboard | life_briefing"
                },
                "name": {"type": "STRING", "description": "Habit/routine/asset/liability name"},
                "title": {"type": "STRING", "description": "Note title / meeting title"},
                "content": {"type": "STRING", "description": "Note content"},
                "transcript": {"type": "STRING", "description": "Meeting transcript text"},
                "query": {"type": "STRING", "description": "Search query / identifier"},
                "tags": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Tags for a note or link"},
                "frequency": {"type": "STRING", "description": "Habit frequency (daily | weekly)"},
                "target_per_week": {"type": "INTEGER", "description": "Habit target per week"},
                "url": {"type": "STRING", "description": "URL to save"},
                "task": {"type": "STRING", "description": "Focus task name"},
                "minutes": {"type": "INTEGER", "description": "Focus session length in minutes"},
                "time": {"type": "STRING", "description": "Routine time HH:MM"},
                "days": {"type": "ARRAY", "items": {"type": "INTEGER"}, "description": "Routine weekdays (0=Mon..6=Sun)"},
                "action_text": {"type": "STRING", "description": "What the routine should do/say"},
                "amount": {"type": "NUMBER", "description": "Money amount"},
                "source": {"type": "STRING", "description": "Income source"},
                "client": {"type": "STRING", "description": "Invoice client"},
                "status": {"type": "STRING", "description": "Status (e.g. pending | paid)"},
                "due": {"type": "STRING", "description": "Invoice due date"},
                "kind": {"type": "STRING", "description": "Asset/liability kind"},
                "id": {"type": "STRING", "description": "Record id / identifier"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "smart_alert",
        "description": (
            "Configure and manage smart alerts. Use when user says 'enable whatsapp alerts', "
            "'set my phone number', 'check alert status', 'send test alert', "
            "'check now', 'enable alerts', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "configure | status | test_alert | check_now | enable | disable"
                },
                "phone_number": {"type": "STRING", "description": "Your phone number (with country code)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "notification",
        "description": (
            "Check and manage notifications. Use when user says 'any notifications', "
            "'check emails', 'whatsapp messages', 'instagram notifications', "
            "'mark all as read', 'notification briefing', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "briefing | mark_all_read | get_all"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "startup_task",
        "description": (
            "Manages startup tasks and milestones. Use when user says 'add startup task', "
            "'complete milestone', 'show startup dashboard', 'what's our runway', "
            "'track metric', 'save pitch draft', 'log partner message', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "add_task | complete_task | dashboard | add_milestone | complete_milestone | log_metric | save_pitch | partner_message | competitor | feature | team | investor"
                },
                "title": {"type": "STRING", "description": "Task/milestone title"},
                "description": {"type": "STRING", "description": "Details"},
                "priority": {"type": "STRING", "description": "low | normal | high | critical"},
                "metric_name": {"type": "STRING", "description": "Metric name (e.g. MRR, users, runway)"},
                "metric_value": {"type": "NUMBER", "description": "Metric value"},
                "partner_name": {"type": "STRING", "description": "Partner name"},
                "investor_name": {"type": "STRING", "description": "Investor name"},
                "feature_name": {"type": "STRING", "description": "Feature name"},
                "team_name": {"type": "STRING", "description": "Team member name"},
                "role": {"type": "STRING", "description": "Role"},
                "name": {"type": "STRING", "description": "General name field"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "work_task",
        "description": (
            "Work productivity: tasks, emails, documents, code snippets. "
            "Use when user says 'add task', 'draft email', 'save document', "
            "'save code snippet', 'daily briefing', 'weekly summary', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "add_task | complete_task | pending_tasks | daily_briefing | weekly_summary | save_email | get_emails | save_document | get_documents | save_snippet | get_snippets | meeting_notes"
                },
                "title": {"type": "STRING", "description": "Task/title"},
                "description": {"type": "STRING", "description": "Details/content"},
                "to": {"type": "STRING", "description": "Email recipient"},
                "subject": {"type": "STRING", "description": "Email subject"},
                "body": {"type": "STRING", "description": "Email body or document content"},
                "priority": {"type": "STRING", "description": "low | normal | high"},
                "doc_type": {"type": "STRING", "description": "note | spec | proposal"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "register_voice",
        "description": (
            "Enrols the current speaker's voice so JARVIS can recognise them "
            "later. Use whenever the user says 'remember my voice', 'learn my "
            "voice', 'this is me', or 'register my voice as [name]'. The voice "
            "sample is taken from what the user just said, so call it as soon "
            "as possible after they speak."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": (
                        "Name to associate with the voice (e.g. 'Mahesh'). "
                        "Optional — omit it to use the user's configured name."
                    )
                }
            }
        }
    },
    {
    "name": "agent_task",
    "description": (
        "Executes complex multi-step tasks that require MULTIPLE DIFFERENT tools. "
        "Always respond to the user in the language they spoke. "
        "Examples: 'research X and save to file', 'find files and organize them', "
        "'fill a form on a website', 'write and test code'. "
        "DO NOT use for simple computer commands like volume, refresh, close, scroll, "
        "minimize, screenshot, restart, shutdown — use computer_settings for those. "
        "DO NOT use if the task can be done with a single tool call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "Complete description of what needs to be accomplished"
            },
            "priority": {
                "type": "STRING",
                "description": "low | normal | high (default: normal)"
            }
        },
        "required": ["goal"]
    }
},
    {
    "name": "computer_control",
    "description": (
        "Direct computer control: type text, click buttons, use keyboard shortcuts, "
        "scroll, move mouse, take screenshots, fill forms, find elements on screen. "
        "Use when the user wants to interact with any app on the computer directly. "
        "Can generate random data for forms or use user's real info from memory."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
            "text":        {"type": "STRING", "description": "Text to type or paste"},
            "x":           {"type": "INTEGER", "description": "X coordinate for click/move"},
            "y":           {"type": "INTEGER", "description": "Y coordinate for click/move"},
            "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
            "key":         {"type": "STRING", "description": "Single key to press e.g. 'enter'"},
            "direction":   {"type": "STRING", "description": "Scroll direction: up | down | left | right"},
            "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
            "seconds":     {"type": "NUMBER", "description": "Seconds to wait"},
            "title":       {"type": "STRING", "description": "Window title for focus_window"},
            "description": {"type": "STRING", "description": "Element description for screen_find/screen_click"},
            "type":        {"type": "STRING", "description": "Data type for random_data: name|email|username|password|phone|birthday|address"},
            "field":       {"type": "STRING", "description": "Field for user_data: name|email|city"},
            "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            "path":        {"type": "STRING", "description": "Save path for screenshot"},
        },
        "required": ["action"]
    }
},

{
    "name": "flight_finder",
    "description": (
        "Searches for flights on Google Flights and speaks the best options. "
        "Use when user asks about flights, plane tickets, uçuş, bilet, etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "origin":       {"type": "STRING",  "description": "Departure city or airport code"},
            "destination":  {"type": "STRING",  "description": "Arrival city or airport code"},
            "date":         {"type": "STRING",  "description": "Departure date (any format)"},
            "return_date":  {"type": "STRING",  "description": "Return date for round trips"},
            "passengers":   {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
            "cabin":        {"type": "STRING",  "description": "economy | premium | business | first"},
            "save":         {"type": "BOOLEAN", "description": "Save results to Notepad"},
        },
        "required": ["origin", "destination", "date"]
    }
},
{
    "name": "hologram",
    "description": (
        "Holographic 3D projector. Renders ANY object the user asks for as a "
        "rotatable, glowing 3D hologram that can be exploded and inspected PART BY PART "
        "(like Iron Man reviewing a build). It has a built-in library (cars, planes, houses, "
        "animals, planets, devices, the Iron Man suit, shapes...) and can invent anything else "
        "on the fly. Use when user says 'show me a car', 'display a dog in hologram', "
        "'show the Earth in 3d', 'project the Iron Man suit', 'show a dragon hologram', "
        "'explode the suit', 'show the wheels', 'close the hologram', etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "show | explode | assemble | show_part | rotate | close | list"
            },
            "object": {
                "type": "STRING",
                "description": "What to display as a hologram (e.g. 'car', 'red car', 'dog', 'Earth', 'Iron Man suit', 'a coffee machine', 'dragon')"
            },
            "part": {
                "type": "STRING",
                "description": "Optional part to highlight after showing (e.g. 'wheels', 'helmet', 'engine')"
            },
            "value": {"type": "BOOLEAN", "description": "For rotate: true = auto-rotate, false = stop"}
        },
        "required": ["action"]
    }
}
]
