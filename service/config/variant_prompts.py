"""Variant generation prompt assembly.

Mirrors ui/src/prompts.ts + ui/src/generation.ts assembly logic in Python so the
FastAPI backend can act on the dropdowns the frontend already exposes:
prompt-type directive, business objective (ABCD), and the shorten-video toggle.

The output of assemble_prompt() is a single string sent to Gemini.
"""

from typing import Optional


# Hook taxonomy locked to the proven categories from the Chai Shots OTT
# Creative Intelligence Report (Sep 2025–Mar 2026). Numbers in parentheses
# are real campaign volume / cost-per-subscription data; they are surfaced
# to Gemini in the prompt so it grounds hook ranking in actual performance.
HOOK_TYPES = [
    "romantic_tension",       # 2647 subs, ₹257 CPS — highest volume
    "conflict_fight",         # 1294 subs, ₹270 CPS
    "character_introduction", # 432 subs, ₹229 CPS — cheapest
    "question_curiosity",     # 580 subs, ₹323 CPS
    "shocking_reveal",        # weak — use sparingly
]

EMOTIONS = ["suspense", "curiosity", "betrayal", "sadness"]

CHARACTER_DYNAMICS = [
    "love_triangle",          # ₹246 CPS
    "romantic_couple",        # ₹295 CPS
    "husband_wife_conflict",  # ₹317 CPS
]


SCORE_MAX_BY_OBJECTIVE: dict[str, int] = {
    "awareness": 17,
    "consideration": 16,
    "action": 18,
    "shorts": 17,
}
DEFAULT_SCORE_MAX = 100  # narrative-coherence scale when no rubric is in use


def get_score_max(business_objective: Optional[str]) -> int:
    """Return the maximum possible score for the active rubric."""
    if not business_objective:
        return DEFAULT_SCORE_MAX
    return SCORE_MAX_BY_OBJECTIVE.get(business_objective, DEFAULT_SCORE_MAX)


PROMPT_DIRECTIVES: dict[str, str] = {
    "default": "Create balanced promo clip variants that capture the show's core appeal while teasing distinct angles.",
    "highlight": "Focus on the most impactful moments and signature beats of the show.",
    "engaging": "Create variants with strong hooks that capture viewer attention immediately.",
    "professional": "Create polished, premium-feeling variants suitable for prestige marketing placements.",
    "social": "Optimize for social media platforms with quick, punchy edits and scroll-stopping openers.",
    "crop-only": "Create variants that only adjust aspect ratio without shortening the video. Include all original segments in their original order.",
}

ASPECT_RATIO_MODIFIER = " Keep all original segments - do not shorten the video, only adjust for aspect ratio."


ABCD_BLOCKS: dict[str, str] = {
    "awareness": """1.  **Role:** Act as a highly analytical show-promo critic (140 IQ). The clip you are evaluating is a short promo cut from a longer-form show (series / film / episode). Score it against the criteria below as a *promo for that show*, not as a product ad. The categories use the ABCD framework but are reinterpreted for show-promo context — they are NOT about brand logos, product features, or transactional CTAs.
    The objective for this rubric is **Awareness** — making people register that this show exists and remember its identity. Reward clips that establish a strong, memorable show identity quickly.

    *   **A - Attention (0-5 points):** Hook + sustained pull.
        *   **Hook Strength (0-2 points):**
            *   **2 points:** Opens on a beat that creates curiosity, intrigue, or emotional pull within the first ~3 seconds (cold-open, signature line, bold visual, mid-action drop-in, unanswered question).
            *   **1 point:** Opening is decent but slow to land or relies on a generic establishing shot.
            *   **0 points:** Opens flat — no hook, exposition or filler in the first beat.
        *   **Audio/Pacing Engagement (0-2 points):**
            *   **2 points:** Score, dialogue, ambient sound, or rhythm of cuts actively pulls the viewer through the clip.
            *   **1 point:** Audio/pacing is functional but not actively engaging.
            *   **0 points:** Audio/pacing flat or sluggish.
        *   **Visual Interest (0-1 point):**
            *   **1 point:** Varied framing, dynamic visuals, distinctive cinematography that maintains visual energy.
            *   **0 points:** Static, repetitive, or visually generic.
    *   **B - Show Identity (0-5 points):** This category replaces "Branding". For a show, identity = the things that make THIS show recognizable: title cards, signature locations, recurring motifs, distinctive cinematography style, character intro shots, signature dialogue cadence. Do NOT deduct points for the absence of a logo, tagline, or product placement — those concepts do not apply.
        *   **Identity Cue Presence (0-2 points):**
            *   **2 points:** The clip contains at least one strong show-identity moment (title card, recurring motif, signature location/visual, character-defining shot).
            *   **1 point:** Some identity cue is present but subtle or fleeting.
            *   **0 points:** No recognizable identity cue.
        *   **Memorable Visual or Line (0-2 points):**
            *   **2 points:** Contains at least one image or line of dialogue that would stick in a viewer's memory after a single watch.
            *   **1 point:** Has a moment that's *almost* memorable but doesn't quite land.
            *   **0 points:** Nothing memorable — generic show beats only.
        *   **Tonal Coherence (0-1 point):**
            *   **1 point:** The clip presents a clear, consistent tonal identity (suspenseful / comedic / romantic / etc.) — a viewer can name the show's vibe after watching.
            *   **0 points:** Tonally muddled or generic.
    *   **C - Connection (0-5 points):** Character / world pull.
        *   **Character Presence (0-2 points):**
            *   **2 points:** A lead is established with enough screen time and close-ups for the viewer to latch on emotionally.
            *   **1 point:** Characters appear but feel interchangeable or distant.
            *   **0 points:** No human anchor / no character POV.
        *   **Stakes or Intrigue (0-1 point):**
            *   **1 point:** The clip plants a clear stake, conflict, or unanswered question — something the viewer wants to see resolved.
            *   **0 points:** No stakes telegraphed.
        *   **World-Texture (0-2 points):**
            *   **2 points:** The clip's setting/world feels specific and lived-in — viewer gets a clear sense of where and when this is happening.
            *   **1 point:** World is implied but generic.
            *   **0 points:** Setting is unclear or feels like anywhere.
    *   **D - Watch-Through Pull (0-2 points):** This category replaces "Call to Action". For a show, the CTA is the clip itself — does it leave the viewer wanting to find and watch the source?
        *   **End-Beat Pull (0-2 points):**
            *   **2 points:** The clip ends on a beat that creates "I want to see what happens" energy — cliffhanger, unresolved question, signature recurring moment, or a bold visual sting.
            *   **1 point:** End-beat is okay but not actively pulling.
            *   **0 points:** Ends flat or on a beat that resolves rather than teases.

    **Remember:** A strong Awareness promo for a show makes the viewer *recognize* the show and *remember* it. A clip with a flat hook, no identity cue, or a resolving ending should score low. A clip with a great hook, strong identity, character intrigue, and a teasing end-beat should score high — even if it has zero "branding" in the product-ad sense. Do not penalize a clip for lacking logos, products, taglines, or transactional CTAs — those are not applicable here.
2.  **Total Score:** Sum the points across all categories. Maximum score is 17.
3.  **Justification:** Provide detailed reasoning IN ENGLISH for the overall score, citing specific scenes from the clip. Be precise about what works and what doesn't in show-promo terms — never penalize for product-ad concepts.""",
    "consideration": """1.  **Role:** Act as a highly analytical show-promo critic (140 IQ). The clip is a promo for a longer-form show. Score it as a *promo for that show* using the criteria below. The objective is **Consideration** — getting the viewer invested enough in characters, world, and narrative pull that they'll choose to watch the source. Reward clips that build emotional investment, not just attention. Do NOT penalize for missing logos, products, taglines, or transactional CTAs — those concepts don't apply.

    *   **A - Attention (0-5 points):** Story-pull and pacing.
        *   **Immersive Story Pull (0-2 points):**
            *   **2 points:** The clip drops the viewer into a story moment that creates immediate curiosity — feels like the middle of something, not a recap.
            *   **1 point:** Tells a story but with too much exposition or feels like a recap.
            *   **0 points:** Plot is unclear or the clip feels like disconnected beats.
        *   **Visual Engagement (0-2 points):**
            *   **2 points:** Varied framing, dynamic shot composition, distinctive cinematography that holds attention.
            *   **1 point:** Visually competent but not arresting.
            *   **0 points:** Static or repetitive.
        *   **Audio/Pacing (0-1 point):**
            *   **1 point:** Score, dialogue rhythm, or sound design actively pulls the viewer forward.
            *   **0 points:** Audio/pacing flat or distracting.
    *   **B - Show Identity (0-3 points):** Reinterprets "Branding" for shows. Identity = recognizable show DNA. Do NOT deduct for absence of logos/products/taglines.
        *   **Show Identity Anchored (0-2 points):**
            *   **2 points:** A signature visual, location, motif, or tonal signature is foregrounded — viewer would recognize this as belonging to a specific show.
            *   **1 point:** Some identity is present but doesn't anchor the clip.
            *   **0 points:** Clip is generic — could belong to any show in the genre.
        *   **Identity Carries to End (0-1 point):**
            *   **1 point:** The closing beat reinforces the show's identity (signature image, recurring motif, character signature, title card if present).
            *   **0 points:** Closes on a generic or off-tone beat.
    *   **C - Connection (0-5 points):** Character + emotional investment.
        *   **Show, Don't Tell (0-2 points):** For a show this means: do we *see* characters acting/feeling vs. having things explained?
            *   **2 points:** Character moments, reactions, and stakes are shown through behavior, expression, and action — not narrated or explained.
            *   **1 point:** Some showing but leans on dialogue exposition.
            *   **0 points:** Heavy on telling/exposition.
        *   **Relatable Hook (0-1 point):**
            *   **1 point:** The character's situation, dilemma, or emotion is something a viewer can latch onto in one watch.
            *   **0 points:** Inaccessible or no clear emotional hook.
        *   **Emotional Pull (0-2 points):**
            *   **2 points:** Generates a real feeling beat — intrigue, dread, sympathy, longing, tension. Viewer cares what happens next.
            *   **1 point:** Tries for an emotional beat but doesn't fully land.
            *   **0 points:** Emotionally flat.
    *   **D - Watch-Through Pull (0-3 points):** Reinterprets "CTA" — for shows the CTA is the clip itself making the viewer want to seek out the source.
        *   **End-Beat Pull (0-2 points):**
            *   **2 points:** Ends on a cliffhanger, unresolved question, or signature moment that creates "what happens next" energy.
            *   **1 point:** End-beat is decent but doesn't actively pull.
            *   **0 points:** Ends flat or on a resolution.
        *   **Investment Earned (0-1 point):**
            *   **1 point:** By the end, viewer has reason to *want* to find this show — the clip planted enough of a story-thread / character-stake to hook a follow-up watch.
            *   **0 points:** No real reason to seek out the source after watching.

    **Remember:** A strong Consideration promo earns the viewer's investment in 30 seconds. Reward emotional pull, character clarity, and a teasing end-beat. Do not deduct points for absence of product-ad concepts (logos, taglines, CTAs, urgency offers) — those are not applicable to show promos.
2.  **Total Score:** Sum across categories. Maximum is 16.
3.  **Justification:** Provide reasoning IN ENGLISH citing specific scenes. Frame all critique in show-promo terms.""",
    "action": """1.  **Role:** Act as a highly analytical show-promo critic (140 IQ). The clip is a promo for a longer-form show. The objective is **Action** — driving the viewer to *go watch the source show right now*. Reward clips that maximize watch-through pull and create immediate "I have to see this" energy. The traditional product-ad framing (logos, incentives, CTAs to "buy now") does NOT apply — for shows, the conversion event is "the viewer goes to find/start the show". Do NOT deduct points for missing product, brand, logo, taglines, urgency offers, or transactional CTAs.

    *   **A - Attention (0-5 points):** Hook + sustained pull.
        *   **Frame Composition (0-1 point):**
            *   **1 point:** Key visual elements (faces, signature shots, on-screen text if any) are well-framed and clearly visible — no important content is cut off or buried.
            *   **0 points:** Important elements awkwardly framed or hard to read.
        *   **Hook Strength (0-2 points):**
            *   **2 points:** Opens on a beat that immediately creates curiosity, intrigue, or emotional pull (cold-open, signature line, mid-action drop-in, bold visual).
            *   **1 point:** Decent opener but slow to land.
            *   **0 points:** Opens flat — no hook, exposition, or filler in the first beat.
        *   **Visual/Pacing Engagement (0-2 points):**
            *   **2 points:** Dynamic framing, varied shots, and pacing that keeps energy high throughout.
            *   **1 point:** Some visual energy but inconsistent.
            *   **0 points:** Static, repetitive, or sluggish.
    *   **B - Show Identity (0-3 points):** Reinterprets "Branding". For a show, identity = recognizable show DNA. Do NOT deduct for absence of logos/products/taglines.
        *   **Show as Hero (0-2 points):** Equivalent of "product as hero" but for a show: is the *show's distinctive identity* (signature visuals, characters, world, tonal mode) what the clip is selling?
            *   **2 points:** The clip clearly foregrounds the show's signature identity — viewer can tell what makes THIS show distinctive.
            *   **1 point:** Identity is present but not foregrounded.
            *   **0 points:** Generic clip — could belong to any show.
        *   **Identity Carries Through (0-1 point):**
            *   **1 point:** Identity is consistent from open to close — the clip ends still feeling like the same show it started as.
            *   **0 points:** Identity drops off or shifts mid-clip.
    *   **C - Connection (0-5 points):** Story clarity + emotional pull + authenticity.
        *   **Clarity (0-2 points):**
            *   **2 points:** Even at 30 seconds, the viewer understands what the clip is *about* — central conflict, character, or hook is clear.
            *   **1 point:** Clear-ish but with gaps.
            *   **0 points:** Confusing or overwhelming.
        *   **Tangible Story-Stakes (0-1 point):**
            *   **1 point:** The clip plants a real, specific stake or question the viewer wants resolved (vs. vague "something is happening" energy).
            *   **0 points:** No tangible stake.
        *   **Authenticity & Tone (0-2 points):**
            *   **2 points:** Tonal voice feels confident and authentic to the show's genre/world. Not overproduced "trailer-voice" cliché. Performances feel real.
            *   **1 point:** Tonal voice is okay but inconsistent or generic.
            *   **0 points:** Feels phony or off-tone.
    *   **D - Watch-Through Pull (0-5 points):** Reinterprets "Direction/CTA". For a show the conversion is "go watch the source" — so this category measures how strongly the clip drives that.
        *   **Pull Lands After Setup (0-1 point):**
            *   **1 point:** The pull moment (cliffhanger / unanswered question / signature beat) lands AFTER the clip has earned the viewer's investment — not before they care.
            *   **0 points:** Pull happens too early or before any setup.
        *   **Pull Strength (0-2 points):**
            *   **2 points:** End-beat creates urgent "what happens next" energy — viewer would actively seek out the source after watching.
            *   **1 point:** End-beat is okay but doesn't actively pull.
            *   **0 points:** Ends flat or on a resolution.
        *   **Distinctive Promise (0-2 points):**
            *   **2 points:** By the end, viewer has a clear sense of what watching the show would *give them* — a specific genre experience, character journey, or world to inhabit.
            *   **1 point:** Promise is implied but vague.
            *   **0 points:** No clear promise of what the show delivers.

    **Remember:** Action promos for shows convert viewers into watchers. Reward clips that clarify what the show is, build emotional investment, and end on a beat that pulls the viewer to seek out the source. Do not deduct for absence of logos, products, transactional CTAs, or limited-time offers — those are product-ad concepts, not show-promo concepts.
2.  **Total Score:** Sum across categories. Maximum is 18.
3.  **Justification:** Provide detailed reasoning IN ENGLISH citing specific scenes. All critique must be framed in show-promo terms.""",
    "shorts": """1.  **Role:** Act as a highly analytical show-promo critic (140 IQ). The clip is a short-form promo for a longer-form show, intended to play in a vertical scrollable feed (YouTube Shorts, Reels, TikTok). The objective is making the clip work in *that* environment — vertical-friendly framing, immediate hook, native pacing, scroll-stopping energy. Score it on its fitness for that placement, not against product-ad criteria. Do NOT deduct for absence of logos, products, taglines, or transactional CTAs.

    *   **A - Attention (0-6 points):** Scroll-stopping hook + native feel.
        *   **Scroll-Stop Hook (0-2 points):**
            *   **2 points:** Within the first ~1.5 seconds the clip presents something arresting enough to stop a thumb mid-scroll — bold visual, signature line, mid-action drop-in, emotional spike.
            *   **1 point:** Hook lands but a beat too late.
            *   **0 points:** Slow open, would get scrolled past.
        *   **Native Feel (0-2 points):**
            *   **2 points:** Feels native to short-form vertical feeds — vertical-friendly framing, intimate scale, doesn't read as a chopped-down TV trailer.
            *   **1 point:** Acceptable for short-form but feels slightly imported.
            *   **0 points:** Reads as a horizontal trailer awkwardly placed in vertical context.
        *   **Pace & Energy (0-1 point):**
            *   **1 point:** Cut rhythm and energy match short-form expectations — crisp, kinetic, no dead air.
            *   **0 points:** Pacing feels TV-trailer slow for the format.
        *   **Replay/Looping Pull (0-1 point):**
            *   **1 point:** Has a moment a viewer might rewind or replay (a beat, line, or visual that rewards a second look).
            *   **0 points:** Linear consumption only — no replay value.
    *   **B - Show Identity (0-3 points):** Reinterprets "Branding". Identity = the show's recognizable DNA — characters, signature visuals, motifs, tonal mode. Do NOT deduct for absence of logos/products/taglines.
        *   **Organic Identity Cues (0-2 points):**
            *   **2 points:** Show identity surfaces organically through visuals, character, and tone — not pasted on as a title card stinger.
            *   **1 point:** Identity is present but feels grafted on.
            *   **0 points:** No clear identity cue.
        *   **Identity Sticks the Landing (0-1 point):**
            *   **1 point:** Final beat reinforces show identity — a signature visual, character moment, or motif that tags the clip as belonging to a specific show.
            *   **0 points:** Closes generic.
    *   **C - Connection (0-5 points):** Character / world / proposition.
        *   **Lead Anchor (0-2 points):**
            *   **2 points:** A character or POV the viewer can latch onto in seconds — a face, voice, or stance that carries the clip.
            *   **1 point:** Character anchor present but distant.
            *   **0 points:** No anchor — clip reads as atmospheric only.
        *   **Story-Beat Integration (0-1 point):**
            *   **1 point:** A clear story beat (conflict, decision, reveal) is integrated into the clip — viewer sees something *happen*, not just vibes.
            *   **0 points:** No clear story beat.
        *   **Clear "What Is This Show" (0-2 points):**
            *   **2 points:** By the end, viewer can name what kind of show this is and what it offers — genre, tone, central idea.
            *   **1 point:** Vibe comes through but specifics are murky.
            *   **0 points:** Unclear — viewer would not know what they're being sold on.
    *   **D - Watch-Through Pull (0-3 points):** Reinterprets "CTA/Direction" for shows. The conversion is "viewer goes to find the source" — not a transactional click.
        *   **Pull End-Beat (0-2 points):**
            *   **2 points:** Closes on a beat that creates "what happens next" energy — cliffhanger, unresolved tease, or signature recurring moment.
            *   **1 point:** End-beat is okay but doesn't actively pull.
            *   **0 points:** Closes flat or on a resolution.
        *   **Visual/Title Tag (0-1 point):** Optional but counts when present — a title card, episode/show name, or signature visual at the end that tells the viewer what to look up.
            *   **1 point:** A clear show-identity tag at the end (title card, signature visual, or recognizable motif) tells the viewer what to seek out.
            *   **0 points:** No identity tag at close.

    **Remember:** Shorts promos for shows live or die on the first 1.5 seconds and the last beat. Reward scroll-stopping hooks, native feel, character clarity, and a teasing close. Do not penalize for missing logos, products, transactional CTAs, or marketing copy.
2.  **Total Score:** Sum across categories. Maximum is 17.
3.  **Justification:** Reasoning IN ENGLISH, citing specific scenes. Frame all critique in show-promo terms.""",
}


SHOW_TRAILER_PROMPT = """**Objective:** Generate {{numVariants}} short promo clips for a Chai Shots OTT show. You are given a **pre-committed hook inventory** from a senior creative strategist. Your job is to BUILD one variant per assigned hook — you do not get to pick new hooks or invent angles. The hook inventory is the source of truth for diversity.

    **CRITICAL UP-FRONT CONSTRAINTS (read before anything else):**
    *   The input is a **show**, not an ad. Each output clip is a **standalone promo for that show**.
    *   You will produce **exactly one variant per hook in the assignment table below**. The number of variants you output must equal the number of rows in the assignment table.
    *   For each variant: the variant's `hook_scene` field MUST equal the assigned hook's `scene` number. **Non-negotiable.**
    *   For each variant: the variant's `angle` field MUST be derived from the assigned hook's tags in the form `{hook_type} | {character_label} | {emotion}`. **Non-negotiable.**
    *   Every clip must follow the proven Chai Shots structure: **Setup → Conflict → Cliffhanger.** Open loop. Never resolve.
    *   **No spoilers.** Do not include climaxes, twist payoffs, finale resolutions, or scenes that reveal "what happens next."
    *   **Do NOT default to the source's final scene.** Source endings are usually spoilers.

    **Performance reference (real Chai Shots campaign data, Sep 2025–Mar 2026):**
    The hooks in your assignment table were already chosen against this data. Your job is to honor the structural rules below so the constructed clip *delivers* on the hook's promise:
    *   Cliffhangers convert. Resolutions don't. End on an unresolved beat.
    *   Setup → Conflict → Cliffhanger is the *universally* winning narrative shape across the top 100 ads.
    *   40-90s clips outperform shorter ones because the narrative has room to land emotional investment before the cliffhanger. Aim for the upper end of the duration range when allowed.
    *   Domestic tension (husband-wife, love triangle) is the dominant converter — when a hook centers on these, lean into it, do not soften it.

    **Phase 1: Variant Construction**

    1.  **Role:** Senior promo editor for Chai Shots. You translate hooks into clips. You do not invent hooks.
    2.  **Read the hook inventory below.** It contains:
        *   `show_summary` — the show's premise.
        *   `characters` — character ids and labels.
        *   `dynamics_present` — which proven character dynamics are in this show.
        *   `hooks` — the full inventory of hook candidates the strategist found.
        *   `assignment` — the EXACT subset of hooks you must build variants for. One variant per row, in order.

    3.  **For each row of the assignment table, construct one variant:**
        *   **Hook scene is fixed.** The first segment of the variant MUST be the assigned hook's `scene`.
        *   **Setup (optional, 0-2 scenes):** Use the assigned hook's `suggested_setup_scenes` as a primary hint. You may swap one out for a different setup scene if it serves the angle better, but no more than 2 setup scenes total. If the hook is strongest as a cold-open, use 0 setup scenes — drop the viewer mid-action. Setup scenes must come BEFORE the hook scene in the variant's segment list.
            * IMPORTANT EXCEPTION: when the hook is a `cold_open` style mid-conflict beat (`conflict_fight` with `open_loop_potential = high`), prefer 0 setup scenes — the strategist's data shows mid-argument cold-opens are among the highest converters.
        *   **Conflict body (1-4 scenes):** Scenes that escalate the hook into a deeper conflict, planting stakes and emotional investment. These come after the hook scene.
        *   **Cliffhanger close (1-2 scenes):** Use the assigned hook's `suggested_cliffhanger_scenes` as a primary hint. The final scene must NOT resolve the conflict — it must leave the viewer with an open loop. If a `suggested_cliffhanger_scene` actually resolves the conflict, swap it for a different non-resolving scene.
        *   **Total segments:** Aim for 4-8 scenes per variant. More is fine if duration permits.
    4.  **Tonal re-cut handling:** If the assignment table contains the SAME hook scene more than once (because the user requested more variants than there were distinct hooks), each repetition is a *tonal re-cut*: same hook scene, but you must use a *different emotional framing*, a *different character POV* where possible, and *largely non-overlapping setup/cliffhanger scenes*. Tonal re-cuts must NOT share the same supporting scene cluster as their sibling — that's the entire point.

    5.  **User directive (light bias only):** {{userPrompt}}
        *   This is a soft bias. The hook inventory is locked; do not override it because of the directive.
        *   If the directive is empty, ignore it.
        *   If the directive is an *exclusion* ("avoid scenes with character X"), drop the offending scenes from supporting/cliffhanger picks but keep the assigned hook scene.

    **Phase 2: Critique (Scoring and Justification)**

    Score each constructed variant against the rubric below. Interpret the rubric in show-promo terms — see the rubric's own role definition.

    {{generationEvalPromptPart}}

    **CRITICAL: ALL evaluation text (reasoning, angle, ABCD analysis) MUST be written in English, regardless of the video language ({{videoLanguage}}). Only the title may be in {{videoLanguage}}.**

    **Hard Constraints (any violation = critical failure for that variant):**
        *   `hook_scene` MUST equal the assigned hook's `scene`.
        *   `angle` MUST be `{hook_type} | {character_label} | {emotion}` from the assigned hook.
        *   `segments[0]` MUST equal `hook_scene`.
        *   First scene of each variant must be unique across the variant set, UNLESS the assignment table explicitly has duplicate hook scenes for tonal re-cuts.
        *   No two variants may share the same `angle` string.
        *   Every scene number used must exist in the original script.
        *   Total duration must fall within {{expectedDurationRange}} seconds.
        *   No spoiler scenes (climax reveal, twist payoff, resolution).

    **Hook Inventory & Assignment Table:**
{{hookInventory}}

    **Original Script:**
{{videoScript}}

    **User Directive:** {{userPrompt}}
    **Desired Duration:** {{desiredDuration}} seconds
    **Expected Duration Range:** {{expectedDurationRange}} seconds
    **Video Language:** {{videoLanguage}}
    **Number of Variants Requested:** {{numVariants}}
"""


ASPECT_RATIO_ONLY_PROMPT = """**Objective:** Generate video variants optimized for different aspect ratios by creating different framing strategies while including ALL scenes from the original video.

    **Instructions:**

    **Phase 1: Expert Aspect Ratio Optimization (Focus: Framing, Cropping, and User Directives)**

    1.  **Role:** Assume the role of an expert video editor specializing in aspect ratio optimization and framing for video ads.
    2.  **Core Task:** Create variants that include ALL scenes from the original video, focusing on how to best frame/crop the content for different aspect ratios while maintaining engagement and message clarity.
    3.  **User Directive Interpretation (Crucial):**
        *   **Input Format:** The user has provided their directive in a single free-form text field: {{userPrompt}}.
        *   **Empty Input (No Directive):** If the {{userPrompt}} field is *empty*, the user has provided *no specific directive*. In this case, create variants for common aspect ratios (16:9, 9:16, 1:1, 4:5).
        *   **Aspect Ratio Preference:** If the user specifies aspect ratios (e.g., "optimize for vertical," "create square version"), prioritize those aspect ratios.
        *   **Framing Guidance:** If the user provides framing guidance (e.g., "focus on faces," "center the product"), apply those preferences in your framing strategy.
    4.  **Key Guidelines (Strictly Adhere):**
        *   **Include ALL Scenes:** Every variant MUST include ALL scenes from the original script in their original order.
        *   **Total Duration:** Each variant should maintain the full duration: {{desiredDuration}} seconds.
        *   **Framing Strategy:** Focus on how to best frame/crop the content for different aspect ratios, not on shortening the video.
        *   **Preserve Key Elements:** Ensure that important visual elements (faces, products, text, logos, brand elements) remain visible and well-framed in each aspect ratio.
        *   **Aspect Ratio Variants:** Create variants for different aspect ratios (e.g., "Vertical 9:16", "Square 1:1", "Horizontal 16:9", "Portrait 4:5").
        *   **Coherent Framing:** Ensure the framing strategy is consistent throughout each variant and maintains visual coherence.

    **Phase 2: Expert Critique (Rigorous Evaluation and Recommendations), Scoring and Justification (Detailed Analysis)**

    {{generationEvalPromptPart}}

    **CRITICAL: ALL evaluation text MUST be written in English, regardless of the video language ({{videoLanguage}}). Only the title may be in {{videoLanguage}}.**

    **Constraints (Strictly Enforce):**
        *   Each variant must include *ALL scenes* from the original script in their original order.
        *   Each variant *must* maintain the full duration: {{desiredDuration}} seconds.
        *   Every scene number used must exist in the original script. All scene numbers must be included.
        *   Focus on framing and cropping strategies, not scene selection.

    **Original Script:**
{{videoScript}}

    **User Directive:** {{userPrompt}}
    **Desired Duration:** {{desiredDuration}} seconds
    **Expected Duration Range:** {{expectedDurationRange}} seconds
    **Video Language:** {{videoLanguage}}
    **Number of Variants Requested:** {{numVariants}}
"""


JSON_OUTPUT_DIRECTIVE = """

    **Output Format (Strictly Enforce — JSON ONLY):**

    Output a single JSON object with a `variants` array. Each variant has these fields:

    ```json
    {
      "variants": [
        {
          "title": "Short title (2-4 words, may be in {{videoLanguage}})",
          "angle": "<thread> | <lead character> | <tone>",
          "hook_scene": 7,
          "structure": "chronological",
          "segments": [7, 12, 18, 25],
          "description": "One sentence teaser, no spoilers.",
          "reasoning": "One paragraph in English: why this angle, what it teases, why it stands apart from the other variants.",
          "estimated_duration": 28.5,
          "score": 14
        }
      ]
    }
    ```

    Field rules:
    *   `segments`: 1-indexed scene numbers from the original script. Must exist in the script.
    *   `hook_scene`: must be the FIRST integer in `segments`. Must be the strongest available opener within this variant's chosen scenes (see Strong Hook Opening rule).
    *   `angle`: short label of form "<thread> | <character> | <tone>". MUST be unique across the variant set.
    *   `hook_scene`: MUST be unique across the variant set (no two variants open on the same scene).
    *   `structure`: REQUIRED. Either `"chronological"` or `"cold_open_flashback"`. The backend will reorder `segments` according to this value, so you do NOT need to manually order setup-before/after the hook in the `segments` array — just pick the right structure label and list the scenes you want to include.
        *   Use `"chronological"` when the hook is naturally early in the source's timeline and the story flows forward (Setup → Conflict → Cliffhanger reads in time order). Best for `character_introduction` hooks and early-act `romantic_tension` hooks.
        *   Use `"cold_open_flashback"` when the hook is a mid-arc punch — drop the viewer into the action first, then flash back to setup that came earlier in the source's timeline, then continue forward. This is one of the highest-CPS Chai Shots structures. Best for `conflict_fight` mid-argument or `shocking_reveal` hooks.
    *   `estimated_duration`: actual sum of selected segment durations in seconds. **Important:** the script may contain multiple segments representing the same moment with different cut boundaries (e.g. one for the visual cut, another for the dialogue cut covering nearly identical time ranges). The backend will dedupe overlapping time windows automatically — so the rendered video may be SHORTER than your raw sum if you pick overlapping segments. Pick non-overlapping coverage where possible.
    *   The total `estimated_duration` MUST fall within {{expectedDurationRange}} seconds.
    *   Do NOT select segments that would push the total above {{maxDuration}} seconds.
    *   `score`: when an ABCD rubric is in use, this is the raw total points earned (per the rubric). When no rubric is in use, it is a 1-100 narrative-coherence score.
    *   `description` and `reasoning` must contain no spoilers.

    Output ONLY the JSON object. No markdown fences, no commentary, no preamble.
"""


def calculate_expected_duration_range(desired: float) -> str:
    """+/-20% range as 'min-max'. Mirrors GenerationHelper.calculateExpectedDurationRange."""
    lo = max(1, int(round(desired * 0.8)))
    hi = max(lo + 1, int(round(desired * 1.2)))
    return f"{lo}-{hi}"


_STRENGTH_RANK = {"high": 0, "medium": 1, "low": 2}

# CPS prior from the Creative Intelligence Report (Sep 2025–Mar 2026).
# Lower value = better historical CPS = preferred when diversity ties.
# Custom (off-taxonomy) values get a neutral mid-rank — neither penalized
# nor preferred. Off-taxonomy values are real and may be the next big thing,
# but absent prior data we don't know.
_HOOK_TYPE_CPS_RANK = {
    "character_introduction": 0,  # ₹229 — cheapest
    "romantic_tension": 1,        # ₹257
    "conflict_fight": 2,           # ₹270
    "question_curiosity": 3,       # ₹323
    "shocking_reveal": 4,          # weakest
}
_EMOTION_CPS_RANK = {
    "betrayal": 0,    # ₹218
    "curiosity": 1,   # ₹261
    "suspense": 2,    # ₹312
    "sadness": 3,     # ₹410
}
_DYNAMIC_CPS_RANK = {
    "love_triangle": 0,           # ₹246
    "romantic_couple": 1,         # ₹295
    "husband_wife_conflict": 2,   # ₹317
}
_NEUTRAL_RANK = 2  # given to off-taxonomy custom values


def _cps_rank(rank_map: dict, value) -> int:
    """Return CPS rank for a category value. Off-taxonomy / null values get a
    neutral middling rank so they aren't auto-promoted or auto-penalized."""
    if not value:
        return _NEUTRAL_RANK
    return rank_map.get(value, _NEUTRAL_RANK)


def _hook_sort_key(h: dict, dynamic_seen: set, hook_type_seen: set, emotion_seen: set) -> tuple:
    """Sort hooks for assignment.

    Priority order (lower = better at every position):
      1. Brings a new dynamic (vs. already-seen)
      2. Brings a new hook_type
      3. Brings a new emotion
      4. open_loop_potential (high > medium > low) — cliffhanger-anchorable
      5. strength (high > medium > low)
      6. CPS prior on hook_type — cheapest converter wins ties
      7. CPS prior on dynamic
      8. CPS prior on emotion

    The CPS prior tiebreaks ensure that when two hooks bring equal diversity
    and equal model-judged strength, the historically better-performing
    category wins. Off-taxonomy custom values get a neutral rank — neither
    auto-promoted nor auto-penalized.
    """
    return (
        0 if h.get("dynamic") and h["dynamic"] not in dynamic_seen else 1,
        0 if h.get("hook_type") and h["hook_type"] not in hook_type_seen else 1,
        0 if h.get("emotion") and h["emotion"] not in emotion_seen else 1,
        _STRENGTH_RANK.get(h.get("open_loop_potential", "low"), 3),
        _STRENGTH_RANK.get(h.get("strength", "low"), 3),
        _cps_rank(_HOOK_TYPE_CPS_RANK, h.get("hook_type")),
        _cps_rank(_DYNAMIC_CPS_RANK, h.get("dynamic")),
        _cps_rank(_EMOTION_CPS_RANK, h.get("emotion")),
    )


def select_hooks_for_assignment(hooks: list[dict], n: int) -> list[dict]:
    """Pick `n` hooks for assignment, prioritizing diversity across dynamic →
    hook_type → emotion, then strength. If `n > len(hooks)`, pad by tonal re-cuts:
    repeat the strongest hooks (the model is told to vary emotion/POV/scenes for repeats).
    """
    if not hooks:
        return []
    pool = list(hooks)
    chosen: list[dict] = []
    dynamic_seen: set[str] = set()
    hook_type_seen: set[str] = set()
    emotion_seen: set[str] = set()

    while pool and len(chosen) < n:
        pool.sort(key=lambda h: _hook_sort_key(h, dynamic_seen, hook_type_seen, emotion_seen))
        pick = pool.pop(0)
        chosen.append(pick)
        if pick.get("dynamic"):
            dynamic_seen.add(pick["dynamic"])
        if pick.get("hook_type"):
            hook_type_seen.add(pick["hook_type"])
        if pick.get("emotion"):
            emotion_seen.add(pick["emotion"])

    # Tonal re-cut padding when N > T.
    if len(chosen) < n:
        # Sort original hooks by strength desc; reuse the strongest first.
        ranked = sorted(
            hooks,
            key=lambda h: (
                _STRENGTH_RANK.get(h.get("open_loop_potential", "low"), 3),
                _STRENGTH_RANK.get(h.get("strength", "low"), 3),
            ),
        )
        i = 0
        while len(chosen) < n and ranked:
            chosen.append(ranked[i % len(ranked)])
            i += 1
    return chosen


def format_hook_inventory_block(inventory: dict, assignment: list[dict]) -> str:
    """Render the Pass-1 inventory + assignment table into the text block that
    will be substituted into Pass 2's {{hookInventory}} placeholder."""
    import json as _json
    return _json.dumps(
        {
            "show_summary": inventory.get("show_summary", ""),
            "characters": inventory.get("characters", []),
            "dynamics_present": inventory.get("dynamics_present", []),
            "hooks": inventory.get("hooks", []),
            "assignment": assignment,
        },
        indent=2,
        ensure_ascii=False,
    )


def assemble_prompt(
    *,
    prompt_option: str,
    custom_prompt: str,
    business_objective: Optional[str],
    shorten_video: bool,
    segments_text: str,
    desired_duration: float,
    expected_duration_range: str,
    video_language: str,
    num_variants: int,
    hook_inventory_block: str = "",
) -> str:
    """Build the Pass-2 (variant construction) Gemini prompt.

    Pass 1 (assemble_hook_inventory_prompt) emits a hook inventory which the
    caller formats and threads in here as `hook_inventory_block`. When
    `hook_inventory_block` is empty (Pass 1 fell back / failed), the SHOW_TRAILER
    template will see an empty hook inventory section — the model is then in
    legacy single-pass mode. This is intentional graceful degradation.
    """
    if prompt_option == "custom":
        directive = (custom_prompt or "").strip()
    else:
        directive = PROMPT_DIRECTIVES.get(prompt_option, PROMPT_DIRECTIVES["default"])

    if not shorten_video and prompt_option != "crop-only":
        directive = (directive + ASPECT_RATIO_MODIFIER).strip()

    outer = ASPECT_RATIO_ONLY_PROMPT if not shorten_video else SHOW_TRAILER_PROMPT
    abcd = ABCD_BLOCKS.get(business_objective or "", "")

    max_duration = f"{desired_duration * 1.5:.1f}"

    body = outer + JSON_OUTPUT_DIRECTIVE
    return (
        body.replace("{{userPrompt}}", directive)
        .replace("{{generationEvalPromptPart}}", abcd)
        .replace("{{videoScript}}", segments_text)
        .replace("{{desiredDuration}}", f"{desired_duration:.1f}")
        .replace("{{expectedDurationRange}}", expected_duration_range)
        .replace("{{videoLanguage}}", video_language)
        .replace("{{numVariants}}", str(num_variants))
        .replace("{{maxDuration}}", max_duration)
        .replace("{{hookInventory}}", hook_inventory_block or "(none — operate in single-pass mode: pick your own hooks per the constraints above, ensuring every variant uses a unique hook scene and unique angle)")
    )


HOOK_INVENTORY_PROMPT = """**Role:** You are a senior creative strategist for Chai Shots OTT, a vertical-format Indian streaming platform. Your job is to scan a long-form show and extract every distinct hook moment that could anchor a high-performing promo clip.

**Your knowledge base (real campaign data, do not deviate):**

The following hook taxonomy is the **strong prior** — these are the patterns proven to convert across our top 100 ads. Default to these when the hook fits. Performance numbers are from real Meta ad campaigns Sep 2025–Mar 2026 (₹ = INR cost per subscription, lower = better):

*   **romantic_tension** — 2647 subscriptions, ₹257 CPS. Highest absolute volume. Forbidden intimacy, charged glances, unrequited longing, jealousy, "almost-kiss" moments.
*   **conflict_fight** — 1294 subscriptions, ₹270 CPS. Mid-argument cold-opens, physical confrontation, loud emotional escalation. Especially powerful when the conflict is domestic.
*   **character_introduction** — 432 subscriptions, ₹229 CPS. **Cheapest converter.** A character revealed in a way that makes the viewer immediately want to know more — a defining gesture, a loaded entrance, a quiet moment of intensity.
*   **question_curiosity** — 580 subscriptions, ₹323 CPS. A specific unanswered question planted in the viewer's mind ("what is on that phone?", "why is she hiding?"). Must be specific — vague mystery does not work.
*   **shocking_reveal** — Weakest performer. Use only when the reveal is genuinely strong; usually outperformed by the four above.

The following emotions are the **strong prior** for emotion tagging (real campaign data):
*   **suspense** — 2342 subs, ₹312 CPS
*   **curiosity** — 2301 subs, ₹261 CPS
*   **betrayal** — 459 subs, ₹218 CPS (cheap; underused)
*   **sadness** — 174 subs, ₹410 CPS (expensive; use sparingly)

The following character dynamics are the **strong prior** for dynamic tagging (real campaign data):
*   **love_triangle** — 1554 subs, ₹246 CPS
*   **romantic_couple** — 1433 subs, ₹295 CPS
*   **husband_wife_conflict** — 1298 subs, ₹317 CPS

**Custom-category escape hatch (use sparingly):** This taxonomy is the prior, not a cage. Our data covers the patterns that converted in the *past* — a future hit could be a category we haven't seen. If a hook in this show genuinely doesn't fit any proven category, you MAY emit a custom value for `hook_type`, `emotion`, or `dynamic` — but ONLY if it is a real distinct category, not a synonym. Do NOT invent `argument` when `conflict_fight` fits. Do NOT invent `mystery` when `question_curiosity` fits. When you DO use a custom value, you must explain in the hook's `rationale` field exactly why none of the proven categories fit. **Default behavior: use the proven categories.** The escape hatch exists for genuinely novel hooks, not for variety's sake.

**Universal narrative rule the report enforces:** Every winning ad follows **Setup → Conflict → Cliffhanger**. The ad establishes a premise, plants a high-stakes domestic/romantic conflict, and cuts BEFORE resolution. This "open loop" is what drives the subscription. Hooks you identify must therefore be ones that can anchor that structure — not climaxes, not resolutions.

**Task:**

You will be given a scene-by-scene script of a Chai Shots show. Produce a JSON inventory of:

1.  A 1-sentence show summary (premise only, no spoilers).
2.  The lead and supporting characters who have enough screen presence to anchor a promo clip. Give each a stable id (`C1`, `C2`, ...) and a short label.
3.  Which of the proven character dynamics (`love_triangle`, `romantic_couple`, `husband_wife_conflict`) are present in the source. Only list ones that are genuinely there.
4.  An exhaustive list of **distinct hook candidates** scattered across the runtime. Each hook is anchored on ONE specific scene number. Two hooks may NOT share the same scene number. Aim for as many *genuinely distinct* hooks as the show contains, with a soft floor of {{numVariants}} and a hard cap of 12. If the show truly has fewer than {{numVariants}} distinct hooks, return what's actually there — do not invent.

**For each hook, you must commit to:**

*   `id`: stable label `H1`, `H2`, ...
*   `scene`: 1-indexed scene number from the source script. Must exist in the script.
*   `hook_type`: prefer one of the 5 proven values above. Custom values allowed only when no proven category genuinely fits — see escape hatch.
*   `emotion`: prefer one of the 4 proven values above. Custom values allowed only when no proven emotion fits — see escape hatch.
*   `dynamic`: prefer one of the 3 proven values above. Use `null` if the hook scene does not center on any character dynamic (e.g., a solo character_introduction). Custom dynamic values allowed when no proven dynamic fits — see escape hatch.
*   `character_ids`: array of character ids from the character list whose presence anchors this hook.
*   `label`: 1-line plain-English description ("wife confronts husband at door over phone call", "young woman caught in stolen-glance moment with someone she shouldn't").
*   `strength`: `"high"` | `"medium"` | `"low"`. High means this hook is genuinely scroll-stopping in the first 1.5 seconds. Be honest — do not inflate.
*   `open_loop_potential`: `"high"` | `"medium"` | `"low"`. Can this anchor a Setup → Conflict → Cliffhanger structure? A scene that resolves a conflict has low open-loop potential. A scene that opens or escalates a conflict has high.
*   `suggested_setup_scenes`: up to 2 scene numbers that would play BEFORE the hook to set it up. Empty array if cold-open is stronger.
*   `suggested_cliffhanger_scenes`: up to 2 scene numbers that would close the clip on an unresolved beat. Must NOT include scenes that resolve the conflict.
*   `rationale`: 1 sentence explaining why this hook works against the report's data — reference which winning pattern it matches.

**CRITICAL constraints (any violation invalidates the inventory):**

*   No hook may use a scene number that does not exist in the source script.
*   No two hooks may share the same `scene` number.
*   No hook may be a climax, twist payoff, or finale resolution — those are spoilers and have low open_loop_potential.
*   `hook_type`, `emotion`, `dynamic` should be drawn from the proven taxonomies above whenever they fit. Custom values are allowed only when justified per the escape-hatch rule.
*   Output ONLY the JSON object below. No markdown fences, no commentary, no preamble.

**Output JSON shape:**

```json
{
  "show_summary": "1-sentence premise.",
  "characters": [
    {"id": "C1", "label": "young wife", "scenes": [3, 4, 11, 12], "role": "lead"}
  ],
  "dynamics_present": ["husband_wife_conflict", "love_triangle"],
  "hooks": [
    {
      "id": "H1",
      "scene": 7,
      "hook_type": "conflict_fight",
      "emotion": "suspense",
      "dynamic": "husband_wife_conflict",
      "character_ids": ["C1", "C2"],
      "label": "wife confronts husband at door about phone call",
      "strength": "high",
      "open_loop_potential": "high",
      "suggested_setup_scenes": [3, 5],
      "suggested_cliffhanger_scenes": [12],
      "rationale": "Mid-argument cold-open with phone evidence — matches the 'Husband Betryal' pattern (452 subs, ₹266 CPS)."
    }
  ]
}
```

**Source Script:**
{{videoScript}}

**Number of Variants Requested:** {{numVariants}}
**Video Language:** {{videoLanguage}}
"""


def assemble_hook_inventory_prompt(
    *,
    segments_text: str,
    num_variants: int,
    video_language: str,
) -> str:
    """Build the Pass 1 prompt that asks Gemini to enumerate hook candidates."""
    return (
        HOOK_INVENTORY_PROMPT
        .replace("{{videoScript}}", segments_text)
        .replace("{{numVariants}}", str(num_variants))
        .replace("{{videoLanguage}}", video_language)
    )
