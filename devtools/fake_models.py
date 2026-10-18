"""Stand-ins for the two heavy models (Whisper and the notes LLM).

They let the real pipeline code (chunking, parsing, merging, progress reporting,
database, API) run in tests and in the demo server without downloading anything.
Only the two functions that touch a model are replaced:

    engine._get_whisper  -> FakeWhisper (returns a scripted transcript)
    engine._chat         -> canned replies shaped like a small instruct model's output
"""

import time
from collections import namedtuple

Segment = namedtuple("Segment", "start end text")
Info = namedtuple("Info", "duration language")

SCRIPT = [
    "Okay, let's get started. Thanks everyone for joining the Atlas launch sync. Today I want to cover the release date, the onboarding redesign, and the beta feedback.",
    "Quick recap: we're targeting the public launch on November 18th, which is about five weeks from now.",
    "Marcus, where are we on the engineering side? Right, so the core features are done. The remaining work is the offline sync and the push notification service.",
    "Offline sync is the risky one. We found two data conflict bugs last week, and I'd estimate eight working days to fix and test them properly.",
    "Push notifications are mostly integration work with the provider. Probably three days once we get the production API keys from IT.",
    "Priya, can you chase IT for those keys? Yes, I'll send the request today, and I'll follow up on Friday if we haven't heard back.",
    "Great. Does the eight days for offline sync still leave room for the QA cycle?",
    "It's tight. QA needs at least one full week of regression testing. Dev, is that right? Yes, a week minimum, ideally ten days with the new payment flow.",
    "So if engineering finishes on October 30th, QA runs until November 10th, leaving a week of buffer. I think November 18th is still realistic.",
    "Let's agree to keep November 18th but add a checkpoint on October 30th. If offline sync isn't done by then, we move the launch to December 2nd.",
    "Everyone okay with that? Sounds good. Agreed. Works for me.",
    "Next topic, the onboarding redesign. Elena, you've been testing the new flow.",
    "Yes. The original onboarding had seven screens and only 54 percent of beta users completed it. The new version has four screens and completion is up to 81 percent in the prototype test.",
    "The biggest change is moving account creation to the end, so people see the value of the app before they sign up.",
    "That's a big improvement. Any engineering concerns? Not really, but we need the final designs by October 21st so we can build it in time.",
    "I can have the final designs and the icon set ready by the 21st. I still need to confirm the illustration style with marketing.",
    "Let's use the new four screen flow for launch. Elena will finalize the assets by October 21st.",
    "One open question: should we localize onboarding for Spanish and French at launch, or after? We haven't decided that yet.",
    "I'd say after launch, but let's ask marketing about the European campaign dates.",
    "Now the beta feedback. Dev, can you summarize? Sure. We had 240 beta testers and 112 pieces of feedback.",
    "The top issue is slow loading on the dashboard, mentioned by 38 testers. The second is that dark mode has unreadable text on the settings page.",
    "Dashboard performance is on my list. I think we can cut load time in half by caching the summary queries.",
    "Great. Marcus, please prioritize the dashboard caching after offline sync. And Dev, can you retest dark mode once Elena's fixes are in?",
    "Will do. I'll retest on October 25th.",
    "Last item, budget. We have eight thousand dollars left for the launch campaign, and marketing wants to spend most of it on paid ads.",
    "I'd rather keep two thousand in reserve in case we have to delay the launch. Let's decide next week.",
    "Okay, to wrap up. Priya requests the API keys from IT, Marcus fixes offline sync by October 30th, Elena delivers designs by the 21st, and Dev retests dark mode on the 25th.",
    "Thanks, everybody. We'll meet again next Tuesday at ten.",
]


def scripted_segments():
    """Timestamps proportional to how long each line takes to say."""
    segments, clock = [], 0.0
    for text in SCRIPT:
        length = max(2.5, len(text) * 0.062)
        segments.append(Segment(round(clock, 2), round(clock + length, 2), " " + text))
        clock += length + 1.1
    return segments, round(clock, 2)


class FakeWhisper:
    def __init__(self, delay=0.0, segments=None, language="en"):
        self.delay, self.language = delay, language
        if segments is None:
            self.segments, self.duration = scripted_segments()
        else:
            self.segments = segments
            self.duration = segments[-1].end if segments else 0.0

    def transcribe(self, path, **kwargs):
        def generate():
            for seg in self.segments:
                if self.delay:
                    time.sleep(self.delay)
                yield seg
        return generate(), Info(self.duration, self.language)


CHUNK_REPLIES = [
    """TOPIC: Launch date and engineering status
SUMMARY: The team confirmed a public launch target of November 18th. Core features are complete, but offline sync carries risk after two data-conflict bugs and push notifications still need production API keys.
KEY POINTS:
- Public launch is targeted for November 18th, about five weeks out.
- Offline sync is the riskiest item: two data-conflict bugs found, roughly eight working days to fix and test.
- Push notifications need about three days of integration once production API keys arrive.
- QA needs at least one full week of regression testing, ideally ten days with the new payment flow.
DECISIONS:
- Keep the November 18th launch date, with a checkpoint on October 30th; if offline sync is not done by then, launch moves to December 2nd.
ACTION ITEMS:
- Request production API keys from IT and follow up on Friday if there is no reply (Owner: Priya; Due: Friday)
- Finish and test the offline sync fixes (Owner: Marcus; Due: October 30th)
QUESTIONS:
- None""",
    """**TOPIC:** Onboarding redesign
**SUMMARY:** Elena presented the redesigned onboarding flow, which cuts seven screens to four and raises prototype completion from 54% to 81%. Account creation now happens at the end of the flow.

**KEY POINTS:**
1. Original onboarding had seven screens and only 54% beta completion.
2. New four-screen flow reached 81% completion in prototype testing.
3. Account creation moves to the end so users see the app's value first.
4. Engineering needs final designs by October 21st to build in time.

**DECISIONS:**
- Use the new four-screen onboarding flow for launch.

**ACTION ITEMS:**
- Deliver final onboarding designs and icon set (Owner: Elena; Due: October 21st)
- Confirm the illustration style with marketing (Owner: Elena; Due: Not specified)

**QUESTIONS:**
- Should onboarding be localized into Spanish and French at launch or after?
- When are the European campaign dates? (ask marketing)""",
    """TOPIC: Beta feedback and launch budget
SUMMARY: Dev summarized 112 pieces of feedback from 240 beta testers, led by slow dashboard loading and unreadable dark-mode text. The group also discussed holding back part of the remaining $8,000 campaign budget.
KEY POINTS:
- 240 beta testers submitted 112 pieces of feedback.
- Slow dashboard loading was the top issue, reported by 38 testers.
- Dark mode has unreadable text on the settings page.
- Caching summary queries could roughly halve dashboard load time.
- $8,000 remains for the launch campaign; marketing wants most of it on paid ads.
DECISIONS:
- None
ACTION ITEMS:
- Prioritize dashboard query caching after offline sync (Owner: Marcus; Due: Not specified)
- Retest dark mode once design fixes land (Owner: Dev; Due: October 25th)
- Decide how much budget to keep in reserve (Owner: Unassigned; Due: Next week)
QUESTIONS:
- Should $2,000 be held in reserve in case the launch is delayed?""",
]

FINAL_REPLY = """TITLE: Atlas Launch Sync: Date, Onboarding and Beta Feedback
OVERVIEW: The team reviewed readiness for the Atlas public launch on November 18th. They kept the date with an October 30th checkpoint tied to the offline sync fixes, adopted the shorter four-screen onboarding flow, and reviewed beta feedback that put dashboard performance and dark-mode readability at the top of the fix list. Owners were assigned for API keys, offline sync, design assets and retesting, and the launch budget reserve will be decided next week."""


def make_fake_chat(delay=0.0):
    state = {"calls": 0}

    def fake_chat(system, user, max_new_tokens=400):
        if delay:
            time.sleep(delay)
        if "TITLE:" in user and "OVERVIEW:" in user:
            return FINAL_REPLY
        reply = CHUNK_REPLIES[state["calls"] % len(CHUNK_REPLIES)]
        state["calls"] += 1
        return reply

    return fake_chat


def install(setter=setattr, whisper_delay=0.0, llm_delay=0.0, chunk_chars=1500):
    """Swap the model-touching functions in `engine` for the stand-ins."""
    import engine

    setter(engine, "_get_whisper", lambda force_cpu=False: FakeWhisper(whisper_delay))
    setter(engine, "_chat", make_fake_chat(llm_delay))
    setter(engine, "CHUNK_CHARS", chunk_chars)
