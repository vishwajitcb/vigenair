"""Variant generation prompt assembly.

Mirrors ui/src/prompts.ts + ui/src/generation.ts assembly logic in Python so the
FastAPI backend can act on the dropdowns the frontend already exposes:
prompt-type directive, business objective (ABCD), and the shorten-video toggle.

The output of assemble_prompt() is a single string sent to Gemini.
"""

from typing import Optional


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


SHOW_TRAILER_PROMPT = """**Objective:** Generate a set of short promo clips for a longer-form show (episode, series, or film), each anchored in a *distinct* angle of the source so a marketing team can pick the most compelling cut for an ad campaign.

    **CRITICAL UP-FRONT CONSTRAINTS (read before anything else):**
    *   The input is a **show**, not an ad. The output clips are **promos for that show**.
    *   Each variant must read as a **separate, standalone clip** — not as a tour of the episode and not as a continuation of the same scene flow as another variant.
    *   **No two variants may share the same anchor** (plot thread, lead character, or tonal mode). Variant collisions are a critical failure.
    *   **No spoilers.** Tease, do not resolve. Do not reveal climaxes, finale beats, deaths, twist payoffs, or "and then X happens" outcomes.
    *   **Do NOT default to including the source's final scene.** The source's ending is usually a spoiler. Only include it if it is non-revealing (e.g., a recurring tag, a stinger, a title card).

    **Instructions:**

    **Phase 1: Expert Promo Clip Construction (Focus: Hooks, Distinct Angles, Spoiler Discipline)**

    1.  **Role:** Assume the role of an expert show-trailer/promo editor. Your job is to find different "ways in" to the same show and build one short clip per angle.
    2.  **Pre-Step — Map the Show Before Cutting:** Before producing any combinations, internally enumerate from the script:
        *   **Plot threads / subplots** present in the source (main storyline, secondary arcs, side beats).
        *   **Lead and supporting characters** with enough screen presence to anchor a clip.
        *   **Tonal modes** the source contains (e.g., suspense, action, comedic, emotional, mysterious, romantic).
        *   **Hookable moments** scattered across the runtime: cold-open-style beats, bold visuals, signature dialogue, surprise reveals (non-spoiler), recurring motifs, character-defining moments.
        Use this map to assign each variant a *unique* (thread, character, tone) cell. Treat the map as a planning artifact — do not output it.
    3.  **User Directive Interpretation:**
        *   **Input Format:** The user's directive arrives in a single free-form text field: {{userPrompt}}.
        *   **Empty Input:** If {{userPrompt}} is empty, follow the "Key Promo Clip Guidelines" below with no additional bias.
        *   **Focus Directive:** If the directive emphasizes specific elements ("focus on the detective subplot", "highlight the romance", "lean into the action beats"), bias *all* variants toward that element while still differentiating them on the other axes (character, tone, specific moment).
        *   **Exclusion Directive:** If the directive excludes elements ("no scenes with character Y", "avoid the courtroom scenes"), absolutely omit those scenes from every variant.
        *   **Ambiguous Input:** Treat as a soft inclusion bias. If unrelated to the show, ignore.
    4.  **Key Promo Clip Guidelines (Strictly Adhere):**
        *   **Strong Hook Opening (Context-Consistent):** Each clip must open on the most attention-grabbing moment *available within the variant's own angle and chosen scenes* — a beat that creates curiosity, intrigue, or immediate emotional pull within the first few seconds (cold-open, signature line, bold visual, mid-action drop-in, emotional spike, unanswered question). The hook must share context with the rest of the clip — same thread, same tone, same world — so the viewer who stays put lands in a coherent continuation, not a bait-and-switch. Do NOT borrow a punchy moment from a different thread or tone just to grab attention; that breaks the angle. **Soft floor, not a hard one:** if the variant's angle genuinely lacks a strong hook scene, pick the strongest opener it does have rather than forcing a flashy mismatch — a coherent clip with a moderate opener beats a punchy opener that doesn't fit.
        *   **One Angle Per Clip:** Each clip is built around a single thread, character, or tonal angle from the pre-step map. Do not try to summarize the whole show inside one clip — that's what the source already is.
        *   **Tease, Don't Resolve:** End on a question, a cliffhanger, an unresolved beat, or a signature recurring moment. Never include the climax, twist payoff, or resolution. If a scene reveals an outcome, it is a spoiler — exclude it.
        *   **Show-Identity Cues (when available):** Title cards, recurring motifs, signature locations, and character intro shots strengthen a promo. Include them when they fit the angle.
        *   **Internal Coherence:** Within a single clip, scenes should flow logically (matching tone, sensible chronological feel) — but the clip as a whole must read as *separate* from any other variant. Two variants telling the same micro-story with different windowing is a failure.
        *   **Target Duration (CRITICAL — must fall within {{expectedDurationRange}}):** Aim for ~{{desiredDuration}} seconds. Sum the per-scene durations explicitly. If over: drop the least-essential scene. If under: add a short scene that fits the angle. Failing the duration range scores 1.
        *   **Use More Than One Scene, Never All Scenes.**

    5.  **Variant Diversity (Hard Constraint, Across the Set):**
        *   **Unique Anchor Per Variant:** Every variant must occupy a different (thread, character, tone) cell from the pre-step map. Two variants whose anchors overlap on all three axes is a critical failure.
        *   **No Centre-of-Gravity Overlap:** If two variants would both be "centered" on the same beat or scene cluster, regenerate one of them around a different angle.
        *   **Coverage First, Tonal Re-Cuts Second:** If the user requests N variants and the show has T distinct threads:
            *   When N ≤ T: assign each variant a different thread (further differentiated by character/tone where possible).
            *   When N > T: cover all T threads first (one variant per thread), then create tonal re-cuts of the most promotable threads — same thread, different lead character or different tonal mode (e.g., an "action cut" of the mystery thread vs. an "emotional cut" of the same thread). Tonal re-cuts must use largely *non-overlapping scenes* from each other.
        *   **Diverse Openers:** No two variants may open on the same scene number.

    **Phase 2: Expert Critique (Rigorous Evaluation and Recommendations), Scoring and Justification (Detailed Analysis)**

    The criteria block below scores the **promo clip itself as an ad for the show** — not the show. When the rubric refers to "the brand," "the product," or "the ad," interpret it as "the show being promoted" and "this promo clip." A strong cold-open hook satisfies "Impactful Opening"; a clear "watch now"-style tease or the show's title/identity satisfies branding and direction criteria.

    {{generationEvalPromptPart}}

    **CRITICAL: ALL evaluation text (reasoning, angle, ABCD analysis) MUST be written in English, regardless of the video language ({{videoLanguage}}). Only the title may be in {{videoLanguage}}.**

    **Constraints (Strictly Enforce):**
        *   Each combination must include *more than one scene* but *never all scenes* from the original script.
        *   Each combination *must* fall within the specified duration range: {{expectedDurationRange}}.
        *   Every scene number used must exist in the original script. Generating a non-existent scene number is a critical failure.
        *   No two combinations in the output set may share the same `angle`, and no two may share the same `hook_scene`.
        *   No combination may contain a spoiler scene (climax reveal, twist payoff, finale resolution).

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
    *   `estimated_duration`: actual sum of selected segment durations in seconds.
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
) -> str:
    """Build the full Gemini prompt.

    Mirrors ui/src/generation.ts:83-89 + the directive-resolution logic in
    frontend/js/pages/job-detail.js getPromptTemplate().
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
    )
