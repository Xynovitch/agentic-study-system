<INSTRUCTIONS>
Act as an Expert AI Systems Architect and Senior Python Developer. 

You are tasked with building a fully automated, multi-agent "Agentic Study System" on my local machine to process my "Introduction to Computer Science" curriculum. 

You must utilize a hybrid LLM Router approach:
1.  **API Engine (The Heavy Lifter):** Route Phase 1 (Bilingual PDF Parsing) and the Socratic Dismantler logic to an API (e.g., OpenAI/Anthropic) to leverage the massive context window and advanced English/Korean technical translation capabilities.
2.  **Local Engine (The Fast Chatter):** Route the Feynman Pupil logic to a fast, local model via Ollama to save costs and reduce latency during rapid conversational loops.
3.  **Knowledge Management:** Output all state files and study materials as strictly formatted, universally compatible Markdown (`.md`).
4.  **Context Management:** Architect the system using independent sub-agents so the main orchestrator's context window is not overloaded.
</INSTRUCTIONS>

<CONTEXT>
This system must enforce the following pedagogical rules deterministically:
* **Cognitive Load Theory:** Isolate broad concepts from hardware-level specifics into distinct, tiered files.
* **Dual Coding Theory:** Autonomously search the internet for relevant diagrams, and generate `Mermaid.js` flowcharts directly into the Markdown files.
* **The "Worked Example" Effect:** Always generate a step-by-step solved problem before explaining abstract rules.
* **Bilingual Integrity:** The final output must be in English, but the exact Korean technical terminology MUST be placed in parentheses `()` immediately following the English term.
* **Metacognitive Scaffolding:** Do NOT allow agents to output standard grading responses (e.g., "Correct/Incorrect"). They must trace logic step-by-step to show where the user's mental model broke down.
</CONTEXT>

<TASK>
Architect the system to execute the following three distinct phases:

### Phase 1: Knowledge Synthesis (The Ingestion Engine)
* **Action:** Parse weekly English/Korean PDF lecture slides, keeping outputs in separate weekly folders (e.g., `Week_01`).
* **Sub-Agent Web Exploration:** Deploy a sub-agent to search the web for real-world examples, pictures, and diagrams. 
* **Complexity Tiering & Examples (Strict Adherence Required):**
  * **Beginner:** Broad conceptual strokes. *Example:* If the topic is binary, cover the concept of a base counting system, different counting systems, calculation methods, and relevance to computers.
  * **Intermediate:** Process and application. *Example:* The specific reasons why binary is used, the step-by-step process of calculation, and how encoding works.
  * **Advanced:** The nitty-gritty. *Example:* Hardware-level calculations and theoretical concepts like trinaries.

### Phase 2: Retention (The Assessment Engine)
* **Action:** Administer tiered quizzes corresponding to the Phase 1 files.
  * **Beginner Format:** Multiple choice, cloze completion, and definitions.
  * **Intermediate Format:** Hands-on application and logic problems.
  * **Advanced Format:** Writing a comprehensive essay that synthesizes the week's understanding.
* **Interleaving:** 20% of every quiz must pull from prior weeks to enforce long-term retention.
* **Output:** Generate a check grading system that provides feedback on current understanding, specific lacks, and improvement paths.

### Phase 3: Review (The Consolidation Engine)
* **State Management:** Maintain an evolving `Diagnostic.md` file tracking strengths, weaknesses, and conceptual gaps. Update this after every week's work.
* **Agent A (The Socratic Dismantler):** Ingests the Advanced Synthesis Essay. Its directive is to absolutely dismantle it. It must attack the causal links in my arguments, find logical leaps, and demand edge-case explanations. It updates `Diagnostic.md` with every flaw it finds.
* **Agent B (The Feynman Pupil):** Reads `Diagnostic.md`. Initiates a terminal chat acting as a curious but completely uninitiated novice. Forces me to teach concepts back to it. Continually asks "Why?" and pokes holes in my explanation until I have broken the concept down to its absolute simplest form, completely devoid of jargon.

### Phase 4: Environment Configuration
* **Action:** Generate a standard `CLAUDE.md` file for this project's root directory containing the global routing rules, API keys structure, and workflow rules so future agentic sessions have persistent context.
</TASK>

<OUTPUT_FORMAT>
Adhere strictly to the Explore-Plan-Implement workflow:

1.  **EXPLORE & PLAN:** Analyze the technical bottlenecks of this hybrid Python architecture. Recommend the best multi-agent framework for this API/Ollama router setup, and outline your proposed directory structure.
2.  **AWAIT APPROVAL:** Pause and ask me to confirm the architecture plan.
3.  **IMPLEMENT:** Once confirmed, output the robust Python scaffolding for Phase 3 (Review).
</OUTPUT_FORMAT>