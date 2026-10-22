"""Tier 1.6 — the tool dispatcher, out of `JarvisLive`.

`_execute_tool` is the one place where a model tool call becomes an action: it
validates arguments, asks the permission gate, runs the action off the event loop
and reports the result. It lives here as a mixin so the voice loop in ``main.py``
is a loop again rather than a 1,900-line file.

The static contract check (``agent.tool_contract``) reads the ``if name == ...``
branches from this file; declarations come from ``jarvis.tools_schema`` and the
permission levels from ``config/autonomy.json``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback

import numpy as np
from google.genai import types

from agent.task_queue import get_queue
from jarvis.text_utils import fmt_args as _fmt_args, owner_name as _owner_name

# Audio I/O in main.py uses the same rate; the voice-id fallback below needs the
# constant without importing the entry point.
SEND_SAMPLE_RATE = 16000

from actions.flight_finder import flight_finder
from actions.open_app         import open_app
from actions.weather_report   import weather_action
from actions.send_message     import send_message
from actions.reminder         import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor import screen_process
from actions.youtube_video    import youtube_video
from actions.cmd_control      import cmd_control
from actions.desktop          import desktop_control
from actions.browser_control  import browser_control
from actions.file_controller  import file_controller
from actions.code_helper      import code_helper
from actions.dev_agent        import dev_agent
from actions.web_search       import web_search as web_search_action
from actions.computer_control import computer_control
from actions.spotify_control  import spotify_control

try:
    from system_state import describe_state as _describe_state
except Exception:  # keep the app bootable if the module is missing
    def _describe_state(*_a, **_k):  # type: ignore
        return ""

from memory.memory_extractor import extract_memory

from memory import AIMemory
from voice_id import (
    identify_speaker, register_speaker,
    warmup as voice_id_warmup,
    is_available as voice_id_available,
)
from companion import check_in, detect_emotion, respond_with_emotion, personal_joke, remember_experience, get_recent_experiences, companion_response
from work_assistant import add_task, complete_task, get_pending_tasks, save_meeting_notes, draft_email as wa_draft_email, get_email_drafts as wa_get_email_drafts, save_code_snippet, get_code_snippets, save_document, get_documents, daily_briefing, weekly_summary
from startup_partner import set_startup_info, log_metric, get_metric_trend, add_milestone, complete_milestone, get_milestones, save_pitch_draft, log_partner_message, get_partner_messages, add_competitor, get_competitors, add_product_feature, get_product_features, add_team_member, get_team, log_investor_update, get_investor_updates, startup_dashboard, strategy_prompt
from notifications import start_monitoring, stop_monitoring, briefing, get_all_notifications, mark_all_read, mark_as_read
from smart_alerts import start_monitoring as start_alert_monitoring, stop_monitoring as stop_alert_monitoring, get_status as get_alert_status, configure as configure_alerts, check_emails_and_alert, send_toast_notification, send_whatsapp_text_alert, is_important_email
from business_tools import add_event, get_events, get_today_events, delete_event, add_github_repo, get_github_repos, log_github_issue, get_github_issues, get_mood_playlist, log_mood_music, scan_document, get_scanned_documents, schedule_meeting, get_meetings, review_code, get_code_reviews, log_water, log_break, get_health_summary, log_expense, get_expenses, get_expense_summary, get_dashboard
from enterprise_tools import create_automation, get_automations, toggle_automation, run_automation, draft_email, get_email_drafts, send_email, configure_email, test_email_connection, add_news_topic, get_news_topics, check_news, get_news_alerts, add_to_watchlist, get_watchlist, get_stock_price, check_price_alerts, add_client, get_clients, update_client_status, add_deal, get_deals, get_crm_summary
from life_tools import add_habit, log_habit, get_habits, habit_status, habits_at_risk, start_focus, end_focus, get_focus_stats, focus_report, save_note, get_notes, search_notes, delete_note, save_link, get_links, start_meeting_recording, stop_meeting_recording, save_transcript, summarize_meeting, get_recordings, add_routine, get_routines, remove_routine, check_due_routines, pop_routine_alerts, start_routine_scheduler, stop_routine_scheduler, add_income, add_invoice, update_invoice_status, add_asset, add_liability, get_net_worth, get_finance_summary, get_finance_dashboard, life_briefing
from hologram import launch as hologram_launch, send_command as hologram_command, is_running as hologram_running
from hologram_models import get_model as hologram_model, save as hologram_save, list_models as hologram_list


class ToolRunnerMixin:

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 TOOL: {name}  ARGS: {args}")
        self.ui.jarvis_think("tool", f"{name}({_fmt_args(args)})")
        if args:
            self.ui.jarvis_think("args",
                                 json.dumps(args, ensure_ascii=False, default=str))

        # --- the permission gate, the same choke point as the background agent ---
        # The user is present and made this request, so a soft `confirm` (or a
        # soft policy-table `block`) is satisfied by attendance; a hard block —
        # kill switch, sandbox escape, refused command, denied destination,
        # non-owner speaker — is refused here too.
        from agent import audit as _audit
        from agent import policy as _policy
        from agent.policy import Level as _Level

        try:
            _gate = _policy.evaluate_live(name, args)
        except Exception as _e:
            # Fail closed: a gate that cannot decide must not allow.
            _gate = None
            print(f"[JARVIS] ⚠️ permission gate error: {_e}")

        if _gate is None or _gate.level is _Level.BLOCK:
            _reason = _gate.reason if _gate is not None else "the permission gate failed"
            print(f"[JARVIS] 🛑 Refused [{name}]: {_reason}")
            self.ui.write_log(f"🛑 [{name}] {_reason}")
            self.ui.jarvis_think("err", f"blocked [{name}]: {_reason}")
            try:
                _audit.record("action_denied", tool=name, parameters=args,
                              level="block", outcome="blocked", detail=_reason)
            except Exception:
                pass
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": f"Refused: {_reason}"},
            )

        loop   = asyncio.get_event_loop()
        result = "Done."
        failed = False
        _tool_started = time.perf_counter()

        try:
            if name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Opened {args.get('app_name')} successfully."

            elif name == "get_open_windows":
                r = await loop.run_in_executor(None, lambda: _describe_state())
                result = r or "No notable windows or apps are currently open."

            elif name == "forget":
                # H4: the user's own data, by their own request. Destructive and
                # irreversible, so policy puts it at `confirm` and the approval
                # modal shows the exact effect before it runs. The dry run is the
                # default action so a bare call reports rather than deletes.
                from agent import forget as _forget

                def _call_forget(_args=args):
                    payload = dict(_args)
                    action = str(payload.pop("action", "report") or "report")
                    if action == "report":
                        return json.dumps(_forget.inventory(), ensure_ascii=False)
                    if action == "export":
                        where = payload.get("path") or None
                        return json.dumps(_forget.export(where), ensure_ascii=False)
                    if action == "forget":
                        include_audit = bool(payload.get("include_audit", True))
                        include_voice = bool(payload.get("include_voiceprints", True))
                        done = _forget.forget_all(include_audit=include_audit,
                                                  include_voiceprints=include_voice)
                        return (f"Forgot {done['total_removed']} records. "
                                f"{json.dumps(done['remaining'], ensure_ascii=False)}")
                    return f"Unknown forget action: {action}"

                result = await loop.run_in_executor(None, _call_forget)

            elif name == "devices":
                # W4: one tool over the device registry. The permission gate has
                # already run above; a result with ok=False is reported as a
                # failure so the model never turns it into a claim of success.
                from agent import devices as _devices

                def _call_devices(_args=args):
                    payload = dict(_args)
                    action = str(payload.pop("action", "list") or "list")
                    target = str(payload.pop("target", "") or "")
                    cmd = str(payload.pop("cmd", "") or "")
                    return _devices.render(
                        _devices.dispatch(action, target=target, cmd=cmd, **payload)
                    )

                result = await loop.run_in_executor(None, _call_devices)

            elif name == "weather_report":
                r = await loop.run_in_executor(
                    None, lambda: weather_action(parameters=args, player=self.ui)
                )
                result = r or f"Weather report for {args.get('city')} delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(parameters=args, player=self.ui)
                )
                result = r or "Browser action completed."

            elif name == "file_controller":
                r = await loop.run_in_executor(
                    None, lambda: file_controller(parameters=args, player=self.ui)
                )
                result = r or "File operation completed."

            elif name == "send_message":
                r = await loop.run_in_executor(
                    None, lambda: send_message(
                        parameters=args, response=None,
                        player=self.ui, session_memory=None
                    )
                )
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(
                    None, lambda: reminder(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Reminder set for {args.get('date')} at {args.get('time')}."

            elif name == "youtube_video":
                r = await loop.run_in_executor(
                    None, lambda: youtube_video(parameters=args, response=None, player=self.ui)
                )
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = (
                    "Vision module activated. "
                    "Stay completely silent — vision module will speak directly."
                )

            elif name == "computer_settings":
                r = await loop.run_in_executor(
                    None, lambda: computer_settings(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Done."

            elif name == "cmd_control":
                r = await loop.run_in_executor(
                    None, lambda: cmd_control(parameters=args, player=self.ui)
                )
                result = r or "Command executed."

            elif name == "desktop_control":
                r = await loop.run_in_executor(
                    None, lambda: desktop_control(parameters=args, player=self.ui)
                )
                result = r or "Desktop action completed."
            elif name == "code_helper":
                r = await loop.run_in_executor(
                    None, lambda: code_helper(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak 
                    )
                )
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(
                    None, lambda: dev_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."
            elif name == "register_voice":
                speaker_name = (args.get("name") or "").strip() or _owner_name()
                voice_id = np.frombuffer(self._snapshot_mic_audio(), dtype=np.int16)
                success = register_speaker(speaker_name, voice_id, sample_rate=SEND_SAMPLE_RATE)
                result = f"Voice registered as '{speaker_name}'." if success else "Voice registration failed."

            elif name == "business":
                action = args.get("action", "")
                if action == "calendar_add":
                    e = add_event(args.get("title", ""), args.get("date", ""), args.get("time", ""), args.get("description", ""))
                    result = f"Event added: {e['title']} on {e['date']} at {e['time']}"
                elif action == "calendar_today":
                    events = get_today_events()
                    result = f"Today: {len(events)} events\n" + "\n".join(f"- {e['time']} {e['title']}" for e in events[:10]) if events else "No events today."
                elif action == "calendar_list":
                    events = get_events(args.get("date", ""))
                    result = f"Events: {len(events)}\n" + "\n".join(f"- {e['date']} {e['time']} {e['title']}" for e in events[:10])
                elif action == "calendar_delete":
                    ok = delete_event(args.get("id", "") or args.get("title", ""))
                    result = "Event deleted." if ok else "Event not found."
                elif action == "github_repos":
                    repos = get_github_repos()
                    result = f"Repos: {len(repos)}\n" + "\n".join(f"- {r['name']}: {r['url']}" for r in repos[:10])
                elif action == "github_add_repo":
                    r = add_github_repo(args.get("name", ""), args.get("url", ""), args.get("description", ""))
                    result = f"Repo added: {r['name']} ({r['url']})"
                elif action == "github_issues":
                    issues = get_github_issues()
                    result = f"Open issues: {len(issues)}\n" + "\n".join(f"- [{i['repo']}] {i['title']}" for i in issues[:10])
                elif action == "github_add_issue":
                    i = log_github_issue(args.get("name", ""), args.get("title", ""), args.get("status", "open") or "open")
                    result = f"Issue logged: {i['title']} in {i['repo']}"
                elif action == "mood_music":
                    mood = args.get("mood", "neutral")
                    playlist = get_mood_playlist(mood)
                    result = f"For {mood} mood: {', '.join(playlist[:3])}"
                elif action == "scan_doc":
                    d = scan_document(args.get("path", ""))
                    result = f"Document scanned: {d.get('text', 'No text found')[:200]}"
                elif action == "meeting_add":
                    m = schedule_meeting(args.get("title", ""), args.get("date", ""), args.get("time", ""), args.get("attendees", []))
                    result = f"Meeting scheduled: {m['title']} on {m['date']} at {m['time']}"
                elif action == "meeting_list":
                    meetings = get_meetings(args.get("date", ""))
                    result = f"Meetings: {len(meetings)}\n" + "\n".join(f"- {m['date']} {m['time']} {m['title']}" for m in meetings[:10])
                elif action == "code_review":
                    r = review_code(args.get("code", ""), args.get("language", "python"))
                    result = f"Code Review Score: {r['score']}/100\nIssues: {len(r['issues'])}\n" + "\n".join(f"- {i}" for i in r['issues'][:5])
                elif action == "health":
                    h = get_health_summary()
                    result = f"Water: {h['water_today_ml']}ml ({h['water_percentage']}%)\nBreaks: {h['breaks_today']}/{h['recommended_breaks']}"
                elif action == "water":
                    w = log_water(args.get("amount", 250))
                    result = f"Water logged. Today: {w['water_today_ml']}ml of {w['goal_ml']}ml"
                elif action == "break":
                    b = log_break()
                    result = f"Break logged. Today: {b['breaks_today']} breaks"
                elif action == "expense_add":
                    e = log_expense(args.get("amount", 0), args.get("category", ""), args.get("description", ""))
                    result = f"Expense logged: ₹{e['amount']} for {e['category']}"
                elif action == "expense_summary":
                    s = get_expense_summary()
                    result = f"Today: ₹{s['today_total']}\nMonth: ₹{s['month_total']}\nCategories: {s['by_category']}"
                elif action == "expense_list":
                    expenses = get_expenses()
                    result = f"Expenses: {len(expenses)}\n" + "\n".join(f"- {e['date']} ₹{e['amount']} {e['category']}" for e in expenses[:10])
                elif action == "dashboard":
                    d = get_dashboard()
                    result = f"Business Dashboard:\n- Health: {d['health']['water_percentage']}% water, {d['health']['breaks_today']} breaks\n- Expenses: ₹{d['expenses']['today_total']} today\n- Calendar: {d['calendar_today']} events today\n- GitHub: {d['open_issues']} open issues"
                else:
                    result = f"Unknown business action: {action}"

            elif name == "enterprise":
                action = args.get("action", "")
                if action == "automation_create":
                    a = create_automation(args.get("name", ""), args.get("trigger", ""), args.get("actions", []))
                    result = f"Automation created: {a['name']} ({len(a['actions'])} actions)"
                elif action == "automation_list":
                    autos = get_automations()
                    result = f"Automations: {len(autos)}\n" + "\n".join(f"- {a['id']} {a['name']} [{'on' if a['active'] else 'off'}]" for a in autos[:10]) if autos else "No automations."
                elif action == "automation_toggle":
                    ok = toggle_automation(args.get("id", ""))
                    result = "Automation toggled." if ok else "Automation not found."
                elif action == "automation_run":
                    r = run_automation(args.get("id", ""))
                    result = f"Automation {r.get('automation', '')} {r['status']}."
                elif action == "email_draft":
                    d = draft_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
                    result = f"Draft saved (id {d['id']}) to {d['to']}, subject '{d['subject']}'."
                elif action == "email_drafts":
                    drafts = get_email_drafts()
                    result = f"Drafts: {len(drafts)}\n" + "\n".join(f"- {d['id']} to {d['to']}: {d['subject']}" for d in drafts[:10])
                elif action == "email_send":
                    ok, msg = send_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
                    result = msg
                elif action == "email_config":
                    c = configure_email(args.get("email", ""), args.get("app_password", ""))
                    result = c.get("note") or c.get("error", "Done.")
                elif action == "email_test":
                    ok, msg = test_email_connection()
                    result = msg
                elif action == "news_add":
                    n = add_news_topic(args.get("topic", ""), args.get("keywords", []))
                    result = f"Now tracking news on '{n['topic']}'."
                elif action == "news_topics":
                    topics = get_news_topics()
                    result = f"News topics: {len(topics)}\n" + "\n".join(f"- {t['topic']}" for t in topics[:10])
                elif action == "news_check":
                    alerts = check_news()
                    result = f"News check complete: {len(alerts)} new items.\n" + "\n".join(f"- {a['title']}" for a in alerts[:5])
                elif action == "news_alerts":
                    alerts = get_news_alerts()
                    result = f"Recent news: {len(alerts)}\n" + "\n".join(f"- {a['title']}" for a in alerts[:5])
                elif action == "watchlist_add":
                    w = add_to_watchlist(args.get("symbol", ""), args.get("name", ""), args.get("alert_price"))
                    result = f"Added {w['symbol']} ({w['name']}) to watchlist."
                elif action == "watchlist_list":
                    wl = get_watchlist()
                    result = f"Watchlist: {len(wl)}\n" + "\n".join(f"- {w['symbol']} ({w['name']})" for w in wl[:10])
                elif action == "stock_price":
                    p = get_stock_price(args.get("symbol", ""))
                    result = f"{p['symbol']}: {p['price']} {p['currency']} ({p['change']}%)"
                elif action == "price_alerts":
                    alerts = check_price_alerts()
                    result = f"Triggered price alerts: {len(alerts)}\n" + "\n".join(f"- {a['symbol']} at {a['current_price']}" for a in alerts[:10])
                elif action == "client_add":
                    c = add_client(args.get("name", ""), args.get("company", ""), args.get("email", ""), args.get("phone", ""), args.get("value", 0))
                    result = f"Client added: {c['name']} ({c['company']}) [{c['status']}]"
                elif action == "client_list":
                    clients = get_clients(args.get("status") or None)
                    result = f"Clients: {len(clients)}\n" + "\n".join(f"- {c['name']} ({c['company']}) [{c['status']}]" for c in clients[:10])
                elif action == "client_status":
                    ok = update_client_status(args.get("id", ""), args.get("status", ""))
                    result = "Client status updated." if ok else "Client not found or invalid status."
                elif action == "deal_add":
                    d = add_deal(args.get("name", ""), args.get("title", ""), args.get("value", 0), args.get("stage", "lead"))
                    result = f"Deal added: {d['title']} for {d['client']} (₹{d['value']}) [{d['stage']}]"
                elif action == "deal_list":
                    deals = get_deals(args.get("stage") or None)
                    result = f"Deals: {len(deals)}\n" + "\n".join(f"- {d['client']} {d['title']} ₹{d['value']} [{d['stage']}]" for d in deals[:10])
                elif action == "crm_summary":
                    s = get_crm_summary()
                    result = f"CRM: {s['total_clients']} clients, {s['active_deals']} deals\nPipeline value: ₹{s['total_pipeline_value']}\nWon: ₹{s['won_value']} ({s['win_rate']:.0f}%)"
                else:
                    result = f"Unknown enterprise action: {action}"

            elif name == "life":
                action = args.get("action", "")
                if action == "habit_add":
                    h = add_habit(args.get("name", ""), args.get("frequency", "daily"), args.get("target_per_week", 7))
                    result = f"Habit tracked: {h['name']} (streak {h['streak']})"
                elif action == "habit_log":
                    h = log_habit(args.get("name", ""))
                    result = f"{h['name']} logged. Streak: {h['streak']} day(s), best {h['best_streak']}."
                elif action == "habits":
                    hs = get_habits()
                    result = "Habits:\n" + "\n".join(f"- {h['name']}: {h['streak']}d streak ({h['this_week']}/{h['target_per_week']} this week)" for h in hs) if hs else "No habits yet."
                elif action == "habit_status":
                    h = habit_status(args.get("name", ""))
                    result = f"{h['name']}: streak {h['streak']}, best {h['best_streak']}, done today: {h['done_today']}" if h else "Habit not found."
                elif action == "habits_at_risk":
                    r = habits_at_risk()
                    result = "Pending today: " + ", ".join(h["name"] for h in r) if r else "All habits done today."
                elif action == "focus_start":
                    f = start_focus(args.get("task", ""), args.get("minutes", 25))
                    result = f"Focus started: {f['task']} for {f['minutes']} minutes."
                elif action == "focus_end":
                    result = end_focus()["message"]
                elif action == "focus_stats":
                    s = get_focus_stats()
                    result = f"Focus: {s['minutes_today']} min today ({s['sessions_today']} sessions), {s['minutes_week']} min this week."
                elif action == "focus_report":
                    result = focus_report()
                elif action == "note_add":
                    n = save_note(args.get("title", ""), args.get("content", ""), args.get("tags", []))
                    result = f"Note saved: {n['title']} ({n['id']})"
                elif action == "note_search":
                    res = search_notes(args.get("query", ""))
                    result = f"Found {len(res)}:\n" + "\n".join(f"- {r.get('title','')}: {(r.get('content') or r.get('url',''))[:60]}" for r in res[:5]) if res else "Nothing found."
                elif action == "notes":
                    ns = get_notes(args.get("name") or None)
                    result = f"Notes: {len(ns)}\n" + "\n".join(f"- {n['title']}" for n in ns[:10]) if ns else "No notes yet."
                elif action == "note_delete":
                    ok = delete_note(args.get("query", "") or args.get("title", ""))
                    result = "Note deleted." if ok else "Note not found."
                elif action == "link_add":
                    l = save_link(args.get("url", ""), args.get("title", ""), args.get("tags", []))
                    result = f"Link saved: {l['title']}"
                elif action == "links":
                    ls = get_links(args.get("name") or None)
                    result = f"Links: {len(ls)}\n" + "\n".join(f"- {l['title']}: {l['url']}" for l in ls[:10]) if ls else "No links saved."
                elif action == "meeting_start":
                    m = start_meeting_recording(args.get("title", "Meeting"))
                    result = f"Recording meeting '{m['title']}'."
                elif action == "meeting_stop":
                    m = stop_meeting_recording(args.get("transcript", ""))
                    if m.get("status") == "none":
                        result = m["message"]
                    else:
                        s = m.get("summary") or {}
                        result = f"Meeting saved: {m['title']}. Summary: {s.get('summary','')[:200]}"
                elif action == "meeting_save":
                    r = save_transcript(args.get("title", "Meeting"), args.get("transcript", ""))
                    s = r.get("summary") or {}
                    result = f"Meeting saved with {len(s.get('action_items',[]))} action item(s)."
                elif action == "meeting_summarize":
                    s = summarize_meeting(args.get("transcript", ""))
                    result = ("Summary: " + s["summary"][:300] +
                              "\nActions: " + "; ".join(s["action_items"][:5]) +
                              "\nDecisions: " + "; ".join(s["decisions"][:5]))
                elif action == "recordings":
                    rs = get_recordings()
                    result = f"Recordings: {len(rs)}\n" + "\n".join(f"- {r['title']} ({r['ended'][:10]})" for r in rs[:10]) if rs else "No recordings."
                elif action == "routine_add":
                    r = add_routine(args.get("name", ""), args.get("time", ""), args.get("action_text", "") or args.get("name", ""), args.get("days"))
                    result = f"Routine set: {r['name']} at {r['time']}."
                elif action == "routines":
                    rs = get_routines()
                    result = "Routines:\n" + "\n".join(f"- {r['time']} {r['name']}" for r in rs) if rs else "No routines set."
                elif action == "routine_remove":
                    ok = remove_routine(args.get("name", "") or args.get("id", ""))
                    result = "Routine removed." if ok else "Routine not found."
                elif action == "routines_due":
                    fired = check_due_routines()
                    result = "Fired: " + ", ".join(f["routine"] for f in fired) if fired else "No routines due right now."
                elif action == "income_add":
                    i = add_income(args.get("amount", 0), args.get("source", ""), args.get("content", ""))
                    result = f"Income logged: \u20b9{i['amount']} from {i['source']}."
                elif action == "invoice_add":
                    inv = add_invoice(args.get("client", ""), args.get("amount", 0), args.get("status", "pending"), args.get("due", ""))
                    result = f"Invoice added: {inv['client']} \u20b9{inv['amount']} [{inv['status']}], due {inv['due'] or 'n/a'}."
                elif action == "invoice_status":
                    ok = update_invoice_status(args.get("client", "") or args.get("id", ""), args.get("status", ""))
                    result = "Invoice status updated." if ok else "Invoice not found."
                elif action == "asset_add":
                    a = add_asset(args.get("name", ""), args.get("amount", 0), args.get("kind", "asset"))
                    result = f"Asset added: {a['name']} \u20b9{a['value']}."
                elif action == "liability_add":
                    l = add_liability(args.get("name", ""), args.get("amount", 0), args.get("kind", "loan"))
                    result = f"Liability added: {l['name']} \u20b9{l['value']}."
                elif action == "net_worth":
                    nw = get_net_worth()
                    result = f"Net worth: \u20b9{nw['net_worth']} (assets \u20b9{nw['assets']}, liabilities \u20b9{nw['liabilities']})."
                elif action == "finance_summary":
                    s = get_finance_summary()
                    result = f"Finance: income \u20b9{s['income_month']} / expenses \u20b9{s['expenses_month']} this month, profit \u20b9{s['profit_month']}, outstanding \u20b9{s['invoices_outstanding']}."
                elif action == "finance_dashboard":
                    result = get_finance_dashboard()
                elif action == "life_briefing":
                    result = life_briefing()
                else:
                    result = f"Unknown life action: {action}"

            elif name == "hologram":
                action = (args.get("action") or "show").lower()
                obj = args.get("object") or args.get("name") or args.get("part")
                part = args.get("part")
                try:
                    if action in ("show", "open", "display", "view", "launch", "project"):
                        if not obj:
                            result = "What shall I project?"
                        else:
                            model = hologram_model(obj)
                            path = hologram_save(model, obj)
                            hologram_launch(model_path=path)
                            result = (f"Projecting {model['name']} as a hologram "
                                      f"({len(model['parts'])} parts).")
                    elif action in ("show_part", "focus", "select"):
                        if not obj:
                            result = "Which object and part?"
                        else:
                            model = hologram_model(obj)
                            path = hologram_save(model, obj)
                            hologram_launch(model_path=path, part=part or obj)
                            result = f"Highlighting the {part or obj}."
                    elif action == "explode":
                        hologram_launch(explode=True)
                        result = "Exploded view engaged."
                    elif action == "assemble":
                        hologram_launch(explode=False)
                        result = "Reassembling."
                    elif action == "rotate":
                        val = args.get("value")
                        hologram_command({"action": "autorotate",
                                          "value": True if val is None else bool(val)})
                        result = "Rotation updated."
                    elif action in ("close", "quit", "stop", "hide"):
                        hologram_command({"action": "quit"})
                        result = "Closing the hologram."
                    elif action in ("list", "library"):
                        names = ", ".join(hologram_list())
                        result = f"I have {len(hologram_list())} built-in objects: {names}."
                    else:
                        result = f"Unknown hologram action: {action}"
                except Exception as e:
                    print(f"[JARVIS] Hologram error: {e}")
                    result = "I couldn't open the holographic display."

            elif name == "smart_alert":
                action = args.get("action", "")
                if action == "configure":
                    config = configure_alerts(args.get("phone_number", ""))
                    result = f"WhatsApp alerts configured. Phone: {config['user_phone']}"
                elif action == "status":
                    s = get_alert_status()
                    result = f"Alerts enabled: {s['enabled']}\nTotal alerts: {s['total_alerts_sent']}\nInterval: {s['check_interval']}s"
                elif action == "test_alert":
                    from smart_alerts import _load_config
                    cfg = _load_config()
                    ok = send_whatsapp_text_alert(cfg["user_phone"], "JARVIS test: WhatsApp alerts are working.")
                    result = "Test WhatsApp alert sent." if ok else "Failed. Check phone number."
                elif action == "check_now":
                    emails = check_emails_and_alert()
                    result = f"Found {len(emails)} important emails." if emails else "No important emails right now."
                elif action == "enable":
                    start_alert_monitoring()
                    result = "WhatsApp alerts enabled."
                elif action == "disable":
                    stop_alert_monitoring()
                    result = "WhatsApp alerts disabled."
                else:
                    result = f"Unknown alert action: {action}"

            elif name == "notification":
                action = args.get("action", "")
                if action == "briefing":
                    result = briefing()
                elif action == "get_all":
                    n = get_all_notifications()
                    result = f"Total unread: {n['total']}\nEmails: {len(n['emails'])}\nWhatsApp: {len(n['whatsapp'])}\nInstagram: {len(n['instagram'])}"
                elif action == "mark_all_read":
                    mark_all_read()
                    result = "All notifications marked as read."
                else:
                    result = f"Unknown notification action: {action}"

            elif name == "startup_task":
                action = args.get("action", "")
                if action == "dashboard":
                    result = json.dumps(startup_dashboard(), indent=2, ensure_ascii=False)
                elif action == "add_task":
                    task = add_task(args.get("title", ""), args.get("priority", "normal"))
                    result = f"Task added: {task['title']}"
                elif action == "complete_task":
                    ok = complete_task(args.get("title", ""))
                    result = "Milestone completed." if ok else "Task not found."
                elif action == "add_milestone":
                    ms = add_milestone(args.get("title", ""), args.get("description", ""))
                    result = f"Milestone added: {ms['title']}"
                elif action == "complete_milestone":
                    ok = complete_milestone(args.get("title", ""))
                    result = "Milestone completed." if ok else "Milestone not found."
                elif action == "log_metric":
                    m = log_metric(args.get("metric_name", ""), args.get("metric_value", 0), args.get("description", ""))
                    result = f"Metric logged: {m['metric']} = {m['value']}"
                elif action == "save_pitch":
                    d = save_pitch_draft(args.get("title", ""), args.get("description", ""))
                    result = f"Pitch draft saved: {d['title']}"
                elif action == "partner_message":
                    m = log_partner_message(args.get("partner_name", ""), args.get("message", args.get("description", "")))
                    result = f"Message logged for {m['partner']}"
                elif action == "competitor":
                    c = add_competitor(args.get("name", ""), args.get("title", ""), args.get("description", ""))
                    result = f"Competitor added: {c['name']}"
                elif action == "feature":
                    f = add_product_feature(args.get("feature_name", args.get("name", "")), args.get("description", ""))
                    result = f"Feature added: {f['name']}"
                elif action == "team":
                    t = add_team_member(args.get("team_name", args.get("name", "")), args.get("role", ""))
                    result = f"Team member added: {t['name']} as {t['role']}"
                elif action == "investor":
                    u = log_investor_update(args.get("investor_name", ""), args.get("update", args.get("description", "")))
                    result = f"Investor update logged: {u['investor']}"
                else:
                    result = f"Unknown startup action: {action}"

            elif name == "work_task":
                action = args.get("action", "")
                if action == "add_task":
                    t = add_task(args.get("title", ""), args.get("priority", "normal"))
                    result = f"Task added: {t['title']}"
                elif action == "complete_task":
                    ok = complete_task(args.get("title", "") or args.get("id", ""))
                    result = "Task marked complete." if ok else "Task not found."
                elif action == "pending_tasks":
                    tasks = get_pending_tasks()
                    result = f"Pending tasks: {len(tasks)}\n" + "\n".join(f"- [{t['priority']}] {t['title']}" for t in tasks[:10])
                elif action == "daily_briefing":
                    b = daily_briefing()
                    result = f"Daily Briefing ({b['date']}):\n- Pending tasks: {b['total_pending_tasks']}\n- High priority: {b['high_priority_tasks']}\n- Meetings today: {b['meetings_today']}\n- Pending emails: {b['pending_emails']}"
                elif action == "weekly_summary":
                    w = weekly_summary()
                    result = f"Week of {w['week_of']}:\n- Completed: {w['tasks_completed']}\n- Pending: {w['tasks_pending']}\n- Meetings: {w['meetings_this_week']}"
                elif action == "save_email":
                    d = wa_draft_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
                    result = f"Email draft saved to {d['to']}"
                elif action == "get_emails":
                    emails = wa_get_email_drafts()
                    result = f"Email drafts: {len(emails)}"
                elif action == "save_document":
                    d = save_document(args.get("title", ""), args.get("description", args.get("body", "")), args.get("doc_type", "note"))
                    result = f"Document saved: {d['title']}"
                elif action == "get_documents":
                    docs = get_documents()
                    result = f"Documents: {len(docs)}"
                elif action == "save_snippet":
                    s = save_code_snippet(args.get("title", ""), args.get("description", args.get("body", "")))
                    result = f"Code snippet saved: {s['description'][:50]}"
                elif action == "meeting_notes":
                    m = save_meeting_notes(args.get("title", ""), args.get("description", args.get("body", "")))
                    result = f"Meeting notes saved: {m['title']}"
                else:
                    result = f"Unknown work action: {action}"

            elif name == "agent_task":
                goal         = args.get("goal", "")
                priority_str = args.get("priority", "normal").lower()

                from agent.task_queue import get_queue, TaskPriority
                priority_map = {
                    "low":    TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high":   TaskPriority.HIGH,
                }
                priority = priority_map.get(priority_str, TaskPriority.NORMAL)

                queue   = get_queue()
                task_id = queue.submit(
                    goal=goal,
                    priority=priority,
                    speak=self.speak,
                )
                self.ui.jarvis_think("sys", f"queued background task "
                                            f"[{task_id}]: {goal}")
                result = f"Task started (ID: {task_id}). I'll update you as I make progress."
            elif name == "spotify_control":
                r = await loop.run_in_executor(
                    None, lambda: spotify_control(parameters=args)
                )
                result = r or "Spotify action completed."
            elif name == "web_search":
                r = await loop.run_in_executor(
                    None, lambda: web_search_action(parameters=args, player=self.ui)
                    )
                result = r or "Search completed."
            elif name == "computer_control":
                r = await loop.run_in_executor(
                    None, lambda: computer_control(parameters=args, player=self.ui)
                )
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(
                    None, lambda: flight_finder(parameters=args, player=self.ui)
                )
                result = r or "Done."

            else:
                result = f"Unknown tool: {name}"
            
        except Exception as e:
            failed = True
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.ui.jarvis_think("err", result)

        print(f"[JARVIS] 📤 {name} → {result[:80]}")
        if not failed:
            self.ui.jarvis_think("result", str(result))

        _tool_ms = (time.perf_counter() - _tool_started) * 1000.0
        try:
            from agent import degrade as _degrade, metrics as _metrics, trace as _trace

            _metrics.observe_ms("tool.call", _tool_ms, tool=name)
            _metrics.inc("tool.failure" if failed else "tool.success", tool=name)
            _trace.record("tool", ms=_tool_ms, ok=not failed, tool=name)
            if not failed:
                _degrade.note_success()
        except Exception:
            pass

        return types.FunctionResponse(
            id=fc.id,
            name=name,
            response={"result": result}
        )

