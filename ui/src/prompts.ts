/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *       https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * This file contains all LLM prompts used for variant generation and evaluation.
 * It is separated from config.ts to prevent deployment scripts from overwriting
 * prompt customizations.
 */

export const PROMPTS = {
  /**
   * ABCD Business Objectives Evaluation Prompts
   * These prompts are used to evaluate video variants against different marketing objectives.
   */
  abcdBusinessObjectives: {
    awareness: {
      displayName: 'Awareness',
      value: 'awareness',
      promptPart: `1.  **Role:** Act as a highly analytical critic (140 IQ), meticulously evaluating each generated script combination against the following Awareness ABCD criteria. For each criterion, assign a score based on how well the video fulfills it, and provide specific recommendations for improvement *only where applicable*.
    *   **A - Attention (0-5 points):**
        *   **Impactful Opening (0-2 points):**
            *   **2 points:** The video begins with a compelling opening that immediately grabs attention within the first 5 seconds, utilizing elements like close-ups, fast pacing, tight framing, and/or off-screen speech.
            *   **1 point:** The opening has some attention-grabbing elements but could be improved with more dynamic visuals or a faster pace.
            *   **0 points:** The opening fails to capture attention within the first 5 seconds.
            *   **Recommendation (If Applicable):** If the opening is deemed weak (e.g., due to wide shots, slow pacing, or lack of engaging elements), *describe a specific visual enhancement*. For example: "The opening scene currently features a wide shot of a person. A more impactful opening would be a close-up of their face, focusing on their eyes or a key expression. This would create immediate engagement with the viewer."
        *   **Audio Engagement (0-2 points):**
            *   **2 points:** The video effectively uses audio elements like a narrator, dialogue, music, and/or sound effects to amplify the story and sustain attention throughout.
            *   **1 point:** The video uses some audio elements, but there's room for improvement in incorporating more engaging sound effects or music.
            *   **0 points:** The video lacks engaging audio elements or has poorly balanced sound.
            *   **Recommendation (If Applicable):** If audio is underutilized, suggest adding a voiceover, relevant sound effects, or background music to enhance the viewing experience. Ensure audio elements complement each other and don't compete.
        *   **Visual Interest (0-1 point):**
            *   **1 point:** The video maintains visual interest throughout with dynamic visuals, varied framing, and captivating imagery.
            *   **0 points:** The video has static or repetitive visuals that fail to keep the viewer engaged.
            *   **Recommendation (If Applicable):** If visuals are static or repetitive, recommend incorporating more dynamic elements like camera movements, transitions, and visually engaging scenes.
    *   **B - Branding (0-5 points):**
        *   **Early Branding (0-2 points):**
            *   **2 points:** The brand's name, logo, product, or tagline is prominently featured within the first 5 seconds.
            *   **1 point:** The brand is present within the first 5 seconds but not in a prominent way.
            *   **0 points:** The brand fails to appear within the first 5 seconds.
            *   **Recommendation (If Applicable):** If brand visibility is weak, *describe how to visually enhance it*. For example: "The brand logo appears small and in the background. It should be enlarged and positioned more centrally, perhaps with a subtle animation to draw attention to it."
        *   **Frequent Branding (0-2 points):**
            *   **2 points:** The brand is integrated at least 3+ times throughout the ad, including the last 5 seconds, using a variety of branding elements.
            *   **1 point:** The brand is present throughout the ad but not frequently enough or with limited variety.
            *   **0 points:** The brand has minimal presence throughout the ad.
            *   **Recommendation (If Applicable):** If branding is infrequent or limited, suggest additional ways to integrate the brand, such as through audio cues, product placement, or tagline displays.
        *   **Branding Variety (0-1 point):**
            *   **1 point:** The video utilizes a variety of branding assets, including the logo, product, tagline, color palette, audio cues, and even mascots or spokespeople.
            *   **0 points:** The video relies on repetitive branding elements.
            *   **Recommendation (If Applicable):** If branding is monotonous, recommend diversifying the use of brand assets. For example, incorporate a brand jingle, use a recognizable brand color scheme, or feature a brand mascot.
    *   **C - Connection (0-5 points):**
        *   **Human Presence (0-2 points):**
            *   **2 points:** The video features people, ideally with close-ups of faces, to create an immediate and relatable connection with viewers.
            *   **1 point:** The video includes people but lacks close-ups or emotional engagement.
            *   **0 points:** The video lacks any human presence.
            *   **Recommendation (If Applicable):** If human presence is lacking, suggest adding close-ups of expressive faces or scenes of people interacting with the product.
        *   **Context and Relevance (0-1 point):**
            *   **1 point:** The video clearly shows how the product or service fits into people's lives by featuring relatable scenarios and diverse characters.
            *   **0 points:** The video lacks context or features unrealistic scenarios.
            *   **Recommendation (If Applicable):** If context is unclear, suggest adding scenes that demonstrate the product's use in everyday situations or highlight its benefits for different demographics.
        *   **Simplicity and Differentiation (0-2 points):**
            *   **2 points:** The video conveys a single, focused message in simple and casual language, while also highlighting what makes the brand or product unique.
            *   **1 point:** The message is somewhat clear but may be too complex or lack differentiation.
            *   **0 points:** The message is unclear, overwhelming, or fails to differentiate the brand.
            *   **Recommendation (If Applicable):** If the message is complex or lacks differentiation, suggest simplifying the language, focusing on a key benefit, and emphasizing the brand's unique selling points.
    *   **D - Direction (0-2 points):**
        *   **Clear Call to Action (0-2 points):**
            *   **2 points:** The video ends with a clear and compelling on-screen call to action that motivates viewers to take the desired next step.
            *   **1 point:** The video includes a call to action, but it could be more prominent or specific.
            *   **0 points:** The video lacks a clear call to action.
            *   **Recommendation (If Applicable):** If the call to action is weak or unclear, suggest making it more visually prominent, using action-oriented language, and providing specific instructions.

    **Remember:** These criteria are interconnected. A strong Awareness video ad excels in all four areas - Attention, Branding, Connection, and Direction. By critically evaluating each aspect and providing specific recommendations, you can help create more effective and impactful video ads.
2.  **Total Score:** Sum up the points for each criterion to calculate the total score (out of 17).
3.  **Justification:** Provide detailed reasoning for the overall score, citing specific examples from the video to support your evaluation. Be precise and analytical, focusing on the strengths and weaknesses of the ad in relation to the Awareness objective.`,
    },
    consideration: {
      displayName: 'Consideration',
      value: 'consideration',
      promptPart: `1.  **Role:** Act as a highly analytical critic (140 IQ), meticulously evaluating each generated script combination against the following Consideration ABCD criteria. For each criterion, assign a score based on how well the video fulfills it, and provide specific recommendations for improvement where applicable.
    *   **A - Attention (0-5 points):**
        *   **Immersive Storytelling (0-2 points):**
            *   **2 points:** The video hooks and sustains attention with an immersive story that goes beyond simply showcasing the product.
            *   **1 point:** The video tells a story, but it could be more engaging or less product-focused.
            *   **0 points:** The video lacks a compelling story or focuses solely on showcasing the product.
            *   **Recommendation (If Applicable):** If the storytelling is weak or product-centric, suggest ways to create a more engaging narrative. For example, introduce a relatable character, build suspense, or incorporate an emotional element.
        *   **Visual Engagement (0-2 points):**
            *   **2 points:** The video maintains visual interest throughout with dynamic visuals, varied framing, and captivating imagery.
            *   **1 point:** The video has some visually engaging elements but could be more dynamic.
            *   **0 points:** The video has static or repetitive visuals.
            *   **Recommendation (If Applicable):** If visuals are static or repetitive, recommend incorporating more dynamic elements like camera movements, transitions, and visually engaging scenes.
        *   **Audio Engagement (0-1 point):**
            *   **1 point:** The video effectively uses audio elements like a narrator, dialogue, music, and/or sound effects to amplify the story and sustain attention.
            *   **0 points:** The video lacks engaging audio elements or has poorly balanced sound.
            *   **Recommendation (If Applicable):** If audio is underutilized, suggest adding a voiceover, relevant sound effects, or background music to enhance the viewing experience. Ensure audio elements complement each other and don't compete.
    *   **B - Branding (0-3 points):**
        *   **Product as Hero (0-2 points):**
            *   **2 points:** The video shifts the branding focus from the company to the product itself, showcasing its features and benefits in detail.
            *   **1 point:** The product is featured, but the branding focus is not entirely on the product.
            *   **0 points:** The video fails to make the product the hero of the ad.
            *   **Recommendation (If Applicable):** If the product isn't the main focus, suggest ways to highlight it. For example, use close-up shots of the product, demonstrate its functionality, and emphasize its key features.
        *   **Consistent Branding (0-1 point):**
            *   **1 point:** The video maintains strong and consistent branding throughout, especially in the last 5 seconds, by featuring the product, logo, and/or audio mentions.
            *   **0 points:** The video has inconsistent or weak branding.
            *   **Recommendation (If Applicable):** If branding is inconsistent or weak, suggest reinforcing it by closing on the product/logo and using audio mentions in the last 5 seconds.
    *   **C - Connection (0-5 points):**
        *   **Show, Don't Just Tell (0-2 points):**
            *   **2 points:** The video clearly demonstrates how the product works and the benefits it offers through product demos, before/afters, or how-to segments.
            *   **1 point:** The video shows some product functionality but could be more demonstrative.
            *   **0 points:** The video relies heavily on telling instead of showing.
            *   **Recommendation (If Applicable):** If the video relies heavily on telling instead of showing, recommend incorporating visual demonstrations of the product in action.
        *   **Relatable Scenarios (0-1 point):**
            *   **1 point:** The video features relatable scenarios and diverse characters that resonate with the target audience.
            *   **0 points:** The video lacks relatable scenarios or features unrealistic characters.
            *   **Recommendation (If Applicable):** If scenarios are unrealistic or characters are unrelatable, suggest making them more authentic and representative of the target audience.
        *   **Direct Engagement (0-2 points):**
            *   **2 points:** The video speaks directly to the consumer, breaks the fourth wall, or uses other techniques to create a sense of authenticity and invite viewers into the story.
            *   **1 point:** The video attempts to engage the viewer but could be more direct or authentic.
            *   **0 points:** The video feels distant or impersonal.
            *   **Recommendation (If Applicable):** If the video feels distant or impersonal, suggest incorporating techniques like direct address, testimonials, or user-generated content to foster a stronger connection.
    *   **D - Direction (0-3 points):**
        *   **Clear Call to Action (0-2 points):**
            *   **2 points:** The video includes a clear and specific call to action, such as "visit site", "sign up", or "buy now", using both visual and audio cues.
            *   **1 point:** The call to action is present but could be more prominent or specific.
            *   **0 points:** The video lacks a clear call to action.
            *   **Recommendation (If Applicable):** If the call to action is weak or unclear, suggest making it more prominent, using action-oriented language, and amplifying it with audio.
        *   **Sense of Urgency (0-1 point):**
            *   **1 point:** The video creates a sense of urgency by highlighting limited-time offers, limited availability, or specific release dates.
            *   **0 points:** The video lacks any sense of urgency.
            *   **Recommendation (If Applicable):** If there is no sense of urgency, suggest incorporating elements like deadlines, limited stock, or exclusive deals to encourage immediate action.

    **Remember:** These criteria are designed to help you critically evaluate YouTube Consideration video ads. By analyzing each element and providing specific recommendations, you can help ensure that these ads effectively move viewers further down the marketing funnel towards conversion.
2.  **Total Score:** Sum up the points for each criterion to calculate the total score (out of 16).
3.  **Justification:** Provide detailed reasoning for the overall score, citing specific examples from the video to support your evaluation. Be precise and analytical, focusing on the strengths and weaknesses of the ad in relation to the Consideration objective.`,
    },
    action: {
      displayName: 'Action',
      value: 'action',
      promptPart: `1.  **Role:** Act as a highly analytical critic (140 IQ), meticulously evaluating each generated script combination against the following Action ABCD criteria. For each criterion, assign a score based on how well the video fulfills it, and provide specific recommendations for improvement where applicable.
    *   **A - Attention (0-5 points):**
        *   **Viewable Area (0-1 point):**
            *   **1 point:** All essential visuals, including text and key elements, are kept within the viewable area of the screen.
            *   **0 points:** Crucial information falls outside the viewable area.
            *   **Recommendation (If Applicable):** If crucial information falls outside the viewable area, suggest repositioning elements to ensure visibility on different screen sizes.
        *   **Immersive Storytelling (0-2 points):**
            *   **2 points:** The video hooks and sustains attention with an immersive story.
            *   **1 point:** The video tells a story, but it could be more engaging.
            *   **0 points:** The video lacks a compelling story.
            *   **Recommendation (If Applicable):** If the storytelling is weak, suggest ways to create a more engaging narrative. For example, introduce a relatable character or build suspense.
        *   **Visual Engagement (0-2 points):**
            *   **2 points:** The video maintains visual interest with dynamic visuals and varied framing.
            *   **1 point:** The video has some visually engaging elements but could be more dynamic.
            *   **0 points:** The video has static or repetitive visuals.
            *   **Recommendation (If Applicable):** If visuals are static or repetitive, recommend incorporating more dynamic elements like camera movements and transitions.
    *   **B - Branding (0-3 points):**
        *   **Product Focus (0-2 points):**
            *   **2 points:** The product is the star of the ad, with minimal distractions.
            *   **1 point:** The product is featured, but other elements distract from it.
            *   **0 points:** The ad fails to make the product the central focus.
            *   **Recommendation (If Applicable):** If other elements overshadow the product, suggest ways to make it the primary focus. For example, use extreme close-ups and integrate branding subtly.
        *   **Seamless Branding (0-1 point):**
            *   **1 point:** Branding is integrated seamlessly, supporting the product story.
            *   **0 points:** Branding feels forced or intrusive.
            *   **Recommendation (If Applicable):** If branding feels forced, suggest more natural ways to incorporate brand elements, like subtle product placement or brand colors.
    *   **C - Connection (0-5 points):**
        *   **Clarity and Credibility (0-2 points):**
            *   **2 points:** The value proposition is clear, precise, and credible, with a focus on a single, strong message.
            *   **1 point:** The message is somewhat clear but may be too complex or lack focus.
            *   **0 points:** The message is unclear or overwhelming.
            *   **Recommendation (If Applicable):** If the message is unclear, suggest simplifying the value proposition and focusing on one key benefit.
        *   **Tangible Benefits (0-1 point):**
            *   **1 point:** The ad illustrates specific benefits and shows how the product enhances the consumer's life.
            *   **0 points:** The ad relies on nebulous claims or doesn't show the product's benefits.
            *   **Recommendation (If Applicable):** If benefits are not clearly demonstrated, suggest adding scenes that show the product in action or highlight its problem-solving capabilities.
        *   **Trust and Authenticity (0-2 points):**
            *   **2 points:** The ad builds trust by showcasing the product in a relatable context, using a confident tone, and providing supporting evidence for claims.
            *   **1 point:** The ad has some trust-building elements but could be more relatable or provide more evidence.
            *   **0 points:** The ad lacks trust signals or feels inauthentic.
            *   **Recommendation (If Applicable):** If the ad lacks trust signals, suggest incorporating elements like user reviews, expert endorsements, or data points to support claims.
    *   **D - Direction (0-5 points):**
        *   **Contextual Call to Action (0-1 point):**
            *   **1 point:** The call to action is presented after the product and its benefits have been established.
            *   **0 points:** The call to action appears too early.
            *   **Recommendation (If Applicable):** If the call to action appears too early, suggest repositioning it to come after the product story.
        *   **Enticing Incentives (0-2 points):**
            *   **2 points:** The ad motivates viewers with enticing incentives, like freebies, discounts, or limited-time offers.
            *   **1 point:** The ad includes incentives, but they could be more compelling.
            *   **0 points:** The ad lacks incentives.
            *   **Recommendation (If Applicable):** If incentives are weak or missing, suggest adding compelling offers to drive conversions.
        *   **Clear Instructions (0-2 points):**
            *   **2 points:** The ad clearly explains how to interact with the brand and under what terms.
            *   **1 point:** The process is somewhat clear but could be more explicit.
            *   **0 points:** The ad fails to provide clear instructions.
            *   **Recommendation (If Applicable):** If the process is unclear, suggest adding specific instructions, visual cues, or demonstrations.

    **Remember:** Action ads are all about driving conversions. By critically evaluating each element and providing specific recommendations, you can help ensure that these ads effectively persuade viewers to take the final step and become customers.
2.  **Total Score:** Sum up the points for each criterion to calculate the total score (out of 18).
3.  **Justification:** Provide detailed reasoning for the overall score, citing specific examples from the video to support your evaluation. Be precise and analytical, focusing on the strengths and weaknesses of the ad in relation to the Action objective.`,
    },
    shorts: {
      displayName: 'YouTube Shorts',
      value: 'shorts',
      promptPart: `1.  **Role:** Act as a highly analytical critic (140 IQ), meticulously evaluating each generated script combination against the following YouTube Shorts ABCD criteria, keeping in mind Shorts' compound nature across Awareness, Consideration, and Action objectives. For each criterion, assign a score based on how well the video fulfills it, and provide specific recommendations for improvement where applicable.
    *   **A - Attention (0-6 points):**
        *   **Authenticity (0-2 points):**
            *   **2 points:** The ad feels native to the Shorts experience, blending seamlessly with organic content and avoiding an overly polished or "ad-like" feel.
            *   **1 point:** The ad has some authentic elements but could be less polished or disruptive.
            *   **0 points:** The ad feels overly polished, disruptive, or like a traditional ad.
            *   **Recommendation (If Applicable):** If the ad feels too polished or disruptive, suggest incorporating more unpolished, "homemade" elements, like user-generated content, spontaneous moments, or lo-fi visuals.
        *   **Personalization (0-2 points):**
            *   **2 points:** The ad adopts a personal, peer-to-peer approach, with talent speaking directly to the viewer using casual language and relatable scenarios.
            *   **1 point:** The ad has some personal elements but could be more conversational or relatable.
            *   **0 points:** The ad feels impersonal or overly scripted.
            *   **Recommendation (If Applicable):** If the ad feels impersonal or overly scripted, suggest having talent address the viewer directly, use casual language, and showcase relatable situations.
        *   **Upbeat Tone (0-1 point):**
            *   **1 point:** The ad maintains an upbeat, fun, and entertaining tone.
            *   **0 points:** The ad lacks energy or feels too serious.
            *   **Recommendation (If Applicable):** If the ad lacks energy, suggest incorporating humor, spontaneous moments, or a faster pace.
        *   **Social Elements (0-1 point):**
            *   **1 point:** The ad encourages social interaction by being shareable, likeable, and participatory.
            *   **0 points:** The ad lacks social elements.
            *   **Recommendation (If Applicable):** If the ad lacks social elements, suggest incorporating interactive elements like polls, challenges, or calls to comment and share.
    *   **B - Branding (0-3 points):**
        *   **Organic Branding (0-2 points):**
            *   **2 points:** Branding is integrated organically into the ad, avoiding a forced or disruptive presence.
            *   **1 point:** Branding is present but could be more seamlessly integrated.
            *   **0 points:** Branding feels forced or disruptive.
            *   **Recommendation (If Applicable):** If branding feels intrusive, suggest more subtle ways to integrate it, like through product placement or brand colors.
        *   **Enduring Branding (0-1 point):**
            *   **1 point:** The ad reinforces branding throughout, particularly at the end.
            *   **0 points:** The ad has weak branding, especially at the end.
            *   **Recommendation (If Applicable):** If branding is weak, suggest adding a strong brand presence in the final scene.
    *   **C - Connection (0-5 points):**
        *   **Talent as Connector (0-2 points):**
            *   **2 points:** The ad features relatable talent who connect with the audience authentically.
            *   **1 point:** The talent is present but could be more relatable or authentic.
            *   **0 points:** The ad lacks relatable talent or features inauthentic personalities.
            *   **Recommendation (If Applicable):** If the talent feels disconnected or inauthentic, suggest using more relatable individuals who embody the target audience.
        *   **Product Integration (0-1 point):**
            *   **1 point:** The product is seamlessly integrated into the ad, with talent demonstrating its use and benefits in a natural and engaging way.
            *   **0 points:** The product feels forced or out of place.
            *   **Recommendation (If Applicable):** If the product feels forced, suggest having talent interact with it more naturally, showcasing its benefits through demos or stories.
        *   **Clear Value Proposition (0-2 points):**
            *   **2 points:** The ad clearly and concisely communicates the product's value proposition and benefits.
            *   **1 point:** The value proposition is present but could be clearer or more concise.
            *   **0 points:** The ad fails to clearly communicate the value proposition.
            *   **Recommendation (If Applicable):** If the value proposition is unclear, suggest focusing on a single key benefit and communicating it simply.
    *   **D - Direction (0-3 points):**
        *   **Compelling Call to Action (0-2 points):**
            *   **2 points:** The ad includes a clear, specific, and relevant call to action.
            *   **1 point:** The call to action is present but could be more compelling or specific.
            *   **0 points:** The ad lacks a clear call to action.
            *   **Recommendation (If Applicable):** If the call to action is weak, suggest making it more prominent, using action-oriented language, and aligning it with the marketing objective.
        *   **Visual Support (0-1 point):**
            *   **1 point:** The call to action is visually supported with elements like text, icons, or graphics.
            *   **0 points:** The call to action lacks visual support.
            *   **Recommendation (If Applicable):** If the call to action lacks visual appeal, suggest adding visual elements like buttons or animations.

    **Remember:** Effective YouTube Shorts ads are tailored to the platform's unique DNA, leveraging authenticity, personalization, and an upbeat tone to connect with viewers. By critically evaluating each element and providing specific recommendations, you can help ensure that these ads effectively achieve their marketing objectives, whether it's building awareness, driving consideration, or ultimately leading to action.
2.  **Total Score:** Sum up the points for each criterion to calculate the total score (out of 17).
3.  **Justification:** Provide detailed reasoning for the overall score, citing specific examples from the video to support your evaluation. Be precise and analytical, focusing on the strengths and weaknesses of the ad in relation to the Shorts format and its combined Awareness, Consideration, and Action objectives.`,
    },
  },

  /**
   * Text Assets Generation Prompts
   */
  textAssetsGenerationPrompt: `You are a leading digital marketer and an expert at crafting high-performing search ad headlines and descriptions that captivate users and drive conversions.
    Follow these instructions in order:

    1. **Analyze the Video**: Carefully analyze the video ad to identify the brand, key products or services, unique selling points, and the core message conveyed.
    2. **Target Audience**: Consider the target audience of the video ad. What are their interests, needs, and pain points? How can the search ads resonate with them?
    {{badExamplePromptPart}}
    3. **Craft Headlines and a Descriptions**: Generate {{desiredCount}} compelling search ad headlines and descriptions based on your analysis. Adhere to these guidelines:
        - **Headlines (Max 40 Characters)**:
            - Include the brand name or a relevant keyword.
            - Highlight the primary benefit or unique feature of the product/service.
            - Create a sense of urgency or exclusivity.
            - Use action words and power words to grab attention.
            - Avoid overselling and nebulous claims.
            - Do not output any question marks or exclamation marks.
        - **Descriptions (Max 90 Characters)**:
            - Expand on the headline, providing additional details or benefits.
            - Include a strong call to action (e.g. "Shop now", "Learn more", "Sign up").
            - Use keywords strategically for better targeting.
            - Maintain a clear and concise message.
            - Avoid overselling and nebulous claims.
            - Do not output more than one question mark or exclamation mark.
    4. **Output Format**: For each generated search ad, output the following components in this exact format:
    Headline: The generated headline.
    Description: The accompanying description.

    Separate each search ad you output by the value: "## Ad".
    Output in {{videoLanguage}}.
    `,

  textAssetsBadExamplePromptPart:
    "3. **Unwanted Example**: Here's an example of a Headline and Description that I DO NOT want you to generate: Headline: {{headline}} Description: {{description}}",

  /**
   * Video Variant Generation Prompts
   */
  generationPrompt: `**Objective:** Generate a set of short promo clips for a longer-form show (episode, series, or film), each anchored in a *distinct* angle of the source so a marketing team can pick the most compelling cut for an ad campaign.

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

    {{{{generationEvalPromptPart}}}}

    **CRITICAL: ALL evaluation text (Reasoning and ABCD sections) MUST be written in English, regardless of the video language ({{videoLanguage}}). Only the Title should be in {{videoLanguage}}. All analysis, reasoning, and ABCD evaluation MUST be in English.**

    **Constraints (Strictly Enforce):**
        *   Each combination must include *more than one scene* but *never all scenes* from the original script {{videoScript}}.
        *   Each combination *must* fall within the specified duration range: {{expectedDurationRange}}.
        *   Every scene number used in a generated combination must exist in the original script {{videoScript}}. Generating a combination that includes a non-existent scene number (e.g., suggesting "5" when the script only has scenes 1-3) is a critical failure and will render the entire output useless.
        *   No two combinations in the output set may share the same anchor (thread, character, tone) cell, and no two may open on the same scene number.
        *   No combination may contain a spoiler scene (climax reveal, twist payoff, finale resolution).
        *   ALL output text except the Title must be in English.

    **Output Format (Strictly Enforce):**

    For each generated combination, present the following information in this *exact* format:
    Title: [Concise and descriptive title in {{videoLanguage}}]
    Scenes: [Comma-separated list of scene numbers included (no "Scene" prefix)]
    Reasoning: [Short but detailed explanation IN ENGLISH. Begin with one sentence naming the variant's anchor in the form "Angle: <thread> | <lead character> | <tone>." Then explain the hook, why this clip stands apart from the other variants, and what it teases without revealing.]
    Score: [Total points earned - sum all points from all ABCD criteria and subcategories. Do NOT convert to 1-5 scale, just output the raw total.]
    Duration: [Calculated duration of the combination in seconds]
    ABCD: [Short but detailed evaluation IN ENGLISH per criterion. Write as continuous flowing text, vertically stacked. Use **bold** for main section headers like "**A - Attention (X/Y points):**" and include subsection point breakdowns like "Impactful Opening (X/Y points):" with line breaks between sections for readability.]

    Separate each combination with the idelimiter: "## Combination".
    Any deviation from this format will be considered a critical failure.


    **Input:**

    Original Script ({{videoScript}}): {{{{videoScript}}}}
    User Directive ({{userPrompt}}): {{{{userPrompt}}}}
    Desired Duration ({{desiredDuration}}): {{{{desiredDuration}}}}
    Expected Duration Range ({{expectedDurationRange}}): {{{{expectedDurationRange}}}}
    Video Language ({{videoLanguage}}): {{{{videoLanguage}}}}


    `,

  aspectRatioOnlyPrompt: `**Objective:** Generate video variants optimized for different aspect ratios by creating different framing strategies while including ALL scenes from the original video.

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

    {{{{generationEvalPromptPart}}}}

    **CRITICAL: ALL evaluation text (Reasoning and ABCD sections) MUST be written in English, regardless of the video language ({{videoLanguage}}). Only the Title should be in {{videoLanguage}}. All analysis, reasoning, and ABCD evaluation MUST be in English.**

    **Constraints (Strictly Enforce):**
        *   Each variant must include *ALL scenes* from the original script {{videoScript}} in their original order.
        *   Each variant *must* maintain the full duration: {{desiredDuration}} seconds.
        *   Every scene number used must exist in the original script {{videoScript}}. All scene numbers must be included.
        *   Focus on framing and cropping strategies, not scene selection.
        *   ALL output text except the Title must be in English.

    **Output Format (Strictly Enforce):**

    For each generated variant, present the following information in this *exact* format:
    Title: [Aspect ratio variant name in {{videoLanguage}} (e.g., "Vertical 9:16", "Square 1:1")]
    Scenes: [Comma-separated list of ALL scene numbers (no "Scene" prefix) - must include every scene]
    Reasoning: [Short but detailed explanation IN ENGLISH of the framing/cropping strategy, how it preserves key elements, and why it's effective for this aspect ratio - write as continuous paragraph text]
    Score: [Total points earned - sum all points from all ABCD criteria and subcategories. Do NOT convert to 1-5 scale, just output the raw total.]
    Duration: [Duration in seconds - should be {{desiredDuration}}]
    ABCD: [Short but detailed evaluation IN ENGLISH per criterion. Write as continuous flowing text, vertically stacked. Use **bold** for main section headers like "**A - Attention (X/Y points):**" and include subsection point breakdowns like "Impactful Opening (X/Y points):" with line breaks between sections for readability.]

    Separate each variant with the delimiter: "## Combination".
    Any deviation from this format will be considered a critical failure.


    **Input:**

    Original Script ({{videoScript}}): {{{{videoScript}}}}
    User Directive ({{userPrompt}}): {{{{userPrompt}}}}
    Desired Duration ({{desiredDuration}}): {{{{desiredDuration}}}}
    Expected Duration Range ({{expectedDurationRange}}): {{{{expectedDurationRange}}}}
    Video Language ({{videoLanguage}}): {{{{videoLanguage}}}}


    `,
};

