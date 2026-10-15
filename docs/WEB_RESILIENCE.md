# Real Web Images resilience

ZeroReels v0.8.1 hardens Wikipedia research and Wikimedia Commons image discovery so an unrelated search result cannot silently replace the user's actual topic.

For hypothetical/editorial titles, the web-media layer derives a stable search subject before research. For example, `What If the Internet Suddenly Disappeared?` is grounded and searched as `Internet`, while the original title remains available to Story Director for narration.

Research grounding now prefers an exact Wikipedia title and rejects unrelated lead pages that only contain a broad keyword. Scene-level Commons queries are built from the stable topic plus safe scene details; unrelated proper names and sensitive terms that are not present in the user's topic are excluded from search expansion.

Real Web Images also no longer throws away an otherwise complete generation merely because Commons runs out of unique files for a later scene. ZeroReels first retries at the topic level with generic real-world fallbacks where appropriate, then may reuse a previously downloaded topic-relevant Commons source with a different edit/motion treatment. Attribution and license metadata remain attached to the reused source and are written to `SOURCES.txt`.

A total network/Commons failure before ZeroReels has obtained any usable real image still reports an error, because silently substituting unrelated material would be worse than stopping.
