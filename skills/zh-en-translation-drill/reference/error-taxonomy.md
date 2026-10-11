# Error Taxonomy

Dictionary of error tags for Chinese-to-English translation. Each tag has 4 fields: what it is / Chinese-thinking cause / fix rule / example. During correction, prefer existing tags; when nothing matches, coin a new kebab-case tag and append it to the end of this file.

---

## Articles

### article-missing-a
- What: missing a/an before a singular countable noun
- Chinese-thinking cause: Chinese has no article system
- Fix rule: singular countable nouns almost always need a/an/the; first mention of a new thing defaults to a/an
- Example: "I have cat" → "I have **a** cat"

### article-missing-the
- What: missing the before something both speakers know
- Chinese-thinking cause: 「那个」 is droppable in Chinese; English "the" is not
- Fix rule: use "the" when both speaker and listener know which one is meant
- Example: "I fixed bug in login page" → "I fixed **the** bug on the login page"

### article-overuse-the
- What: using "the" for generic concepts
- Chinese-thinking cause: 「的」-structures create a felt need for a determiner
- Fix rule: no "the" with generic plurals or uncountable nouns
- Example: "the society needs the trust" → "society needs trust"

## Nouns and number

### plural-missing-s
- What: missing -s on a countable plural
- Chinese-thinking cause: Chinese marks plural through context, not word form
- Fix rule: more than one → must have -s
- Example: "three customer" → "three customers"

## Verbs

### verb-tense-flat
- What: present tense where past tense belongs
- Chinese-thinking cause: Chinese relies on words like 「昨天」; the verb never changes form
- Fix rule: past, completed action → past tense. Time words cannot substitute for inflection
- Example: "yesterday I go to the meeting" → "yesterday I **went** to the meeting"

### third-person-s
- What: missing -s on third-person singular present
- Chinese-thinking cause: Chinese verbs don't inflect for person
- Fix rule: he/she/it + verb → verb takes -s
- Example: "he run fast" → "he run**s** fast"

### to-plus-ing
- What: -ing after infinitive "to"
- Chinese-thinking cause: conflating 「去做某事」 (go do something) with 「在做某事」 (be doing something)
- Fix rule: infinitive to + base verb form
- Example: "help me to refactoring" → "help me **refactor**"

### passive-avoided
- What: forcing an active sentence where passive belongs
- Chinese-thinking cause: 「被」 sentences carry negative connotation in Chinese, so they get avoided
- Fix rule: when the agent is unimportant or unknown, English prefers the passive or an inanimate subject
- Example: "People widely use this method" → "This method **is widely used**"

## Sentence structure

### pronoun-it-missing
- What: missing dummy subject "it"
- Chinese-thinking cause: Chinese allows subjectless sentences
- Fix rule: English sentences need a subject; weather/time/evaluation use "it"
- Example: "is raining" → "**It**'s raining"

### embedded-question-word-order
- What: question word order inside an object clause
- Chinese-thinking cause: Chinese questions and statements share the same order
- Fix rule: once a question is embedded, revert to statement order
- Example: "I need to know what's that mean" → "I need to know what that **means**"

### run-on-comma-splice
- What: comma joining two complete sentences (literal translation of Chinese run-on chains)
- Chinese-thinking cause: Chinese commas can chain on indefinitely
- Fix rule: between English independent clauses use a period / semicolon / conjunction — never a bare comma
- Example: "It was raining, I stayed home" → "It was raining, **so** I stayed home."

### subject-swallow
- What: subjectless literal translation (Chinese drops the subject, so English drops it too)
- Chinese-thinking cause: Chinese topic chains omit subjects freely
- Fix rule: every English clause needs an explicit subject
- Example: "Learned a lot from this project" → "**I** learned a lot from this project"

### because-so-double
- What: using "because" and "so" together
- Chinese-thinking cause: 「因为……所以……」 always comes as a pair
- Fix rule: English takes only one causal connector
- Example: "Because it rained, so we cancelled" → "Because it rained, we cancelled"

### word-order-adjective-after-noun
- What: wrong modifier placement or scrambled relative clause
- Chinese-thinking cause: Chinese modifiers always precede the noun; long front-loaded modifiers translate into top-heavy English
- Fix rule: long modifiers go after the noun (prepositional phrase / clause); short adjectives go before
- Example: "the people who work in this field" ≠ "this field's work people"

## Word choice

### collocation-wrong-partner
- What: grammatically fine, wrong collocation
- Chinese-thinking cause: literal word-for-word mapping of Chinese verb-object pairs
- Fix rule: check the native fixed collocation; collocations are set phrases
- Example: "do research" → "**conduct** research"; "big growth" → "**significant** growth"

### literal-translation-chinglish
- What: word-for-word translation producing an expression that doesn't exist in English
- Chinese-thinking cause: habit of character-by-character mapping
- Fix rule: first ask "how would a native speaker express this meaning", then "how does it translate literally"
- Example: "People mountain people sea" → "huge crowds"; "add oil" → "keep going / you got it"

### register-mismatch
- What: register mismatch (spoken phrasing in writing, or the reverse)
- Chinese-thinking cause: the spoken/written boundary sits in a different place in Chinese, and formality differences don't survive translation
- Fix rule: judge the scene first (email / paper / chat), then pick the register
- Example: "I wanna know" in a formal email → "I would like to know"

### preposition-about-vs-with
- What: confusing with/about
- Chinese-thinking cause: 「跟」 maps to both "with" and "about"
- Fix rule: with = the person you talk to; about = the topic
- Example: "talk with that" → "talk **about** that"

## Spelling and confusables

### spelling-typo
- What: simple spelling slip
- Chinese-thinking cause: none (typing error)
- Fix rule: scan every verb's spelling once before submitting
- Example: "wachted" → "**watched**"

### rest-vs-reset
- What: confusing rest (break) and reset (restore)
- Chinese-thinking cause: similar sounds invite blending; "reset" is the 重置 in "reset your password"
- Fix rule: taking a break = rest; resetting a device/password = reset
- Example: "take a reset" → "take a **rest**"

## Time and frequency

### time-adverbial-order
- What: stiff or split time adverbials
- Chinese-thinking cause: splitting phrases like 「昨天下午」 and translating each part separately
- Fix rule: fixed English time phrases are written as one unit: yesterday afternoon / last Friday evening
- Example: "in the afternoon yesterday" → "**yesterday afternoon**"

### everyday-vs-every-day
- What: confusing everyday (adjective, "ordinary") and every day (adverb, "daily")
- Chinese-thinking cause: 「每天」 gets mapped to the single word "everyday"
- Fix rule: as an adverb use the two words "every day"; "everyday" is only attributive (everyday life). 「每天早上」 = every morning
- Example: "everday morning" → "**every morning**"

## Nouns and number

### there-be-agreement-nearest
- What: wrong verb after "there be" with a mixed singular/plural list
- Chinese-thinking cause: 「有」 doesn't inflect for number; nearest-noun agreement is an English-specific rule
- Fix rule: the verb agrees with the nearest noun; in speech, open with "There's" for singular
- Example: "There are an apple and two oranges" → "**There's an apple** and two oranges"

### source-misread
- What: misreading quantities/details in the source text
- Chinese-thinking cause: none (reading slip)
- Fix rule: circle the numbers in the source before writing
- Example: two oranges translated as "three oranges" → "**two** oranges"

## Verbs

### modal-plus-past-form
- What: past-tense form after a modal verb
- Chinese-thinking cause: 「能到」 — the 到 never inflects; English requires the base form after "can"
- Fix rule: can/could/will/must + base verb form
- Example: "I can arrived" → "I can **get/arrive**"

### modal-mixed-structure
- What: two structures fused into one (can + be free to)
- Chinese-thinking cause: word-for-word translation blends multiple candidate structures together
- Fix rule: use one structure at a time: can + base form, or be free to + verb; for offering, just say "help yourself"
- Example: "you can free to taste" → "**help yourself**"

### infinitive-after-want
- What: -ing after want/need/hope
- Chinese-thinking cause: the 「做」 in 「想做」 doesn't inflect
- Fix rule: want/need/hope/decide + to do
- Example: "I want taking" → "I want **to take**"

### intransitive-verb-object
- What: direct object after an intransitive verb
- Chinese-thinking cause: literal 「到了它」; "arrive" is intransitive
- Fix rule: arrive at + place, or switch to "get there"
- Example: "arrived it" → "**get there** / arrive **at** it"

## Sentence structure

### distance-close-structure
- What: failed literal translation of 「A 离 B 很近」 (A is close to B) — invented "this" subject + misused "between"
- Chinese-thinking cause: Chinese allows a dropped subject; 「离」 gets mapped to "between"
- Fix rule: A is close to B; or "I live close to / a ten-minute walk from B"
- Example: "this's close between my home and company" → "**My home is close to the office**"

---

## New tag template

```
### new-label-name
- What: ……
- Chinese-thinking cause: ……
- Fix rule: ……
- Example: "……" → "……"
```

### finite-verb-missing-ing
- What: an -ing form used as the predicate; the sentence has no conjugated main verb
- Chinese-thinking cause: Chinese verbs have no inflection — 「跑步」 is both the base form and a complete predicate — so it gets translated as "running" and the sentence feels complete
- Fix rule: a present-tense statement needs a conjugated verb (add -s for third-person singular); -ing only follows verbs like be / go
- Example: "My sister running every evening" → "My sister **runs** every evening"

### progressive-for-habitual
- What: progressive tense for a long-term job/habit
- Chinese-thinking cause: the 「在」 of 「在……工作」 is a location/state marker, mistaken for the progressive "currently"
- Fix rule: long-term states → simple present; progressive only for right-now/temporary action (He's working from home today)
- Example: "His brother is working at a hospital" → "His brother **works** at a hospital"

### base-form-after-aux
- What: main verb keeps its inflection after an auxiliary (or fails to revert to base form)
- Chinese-thinking cause: Chinese negation just adds 「不」 and leaves the verb alone; English moves the inflection onto the auxiliary (does), so learners inflect in both places or neither
- Fix rule: inflection appears exactly once, on the auxiliary: doesn't/don't/can/will + base verb
- Example: "don't works" → "doesn't **work**"

### habitual-time-noun-plural
- What: missing plural on habitual time nouns
- Chinese-thinking cause: 「周末」「工作日」 have no singular/plural distinction
- Fix rule: habitual "every/whenever" time expressions take the plural: on weekends / on weekdays
- Example: "on weekend" → "on weekend**s**"

### transitive-verb-extra-prep
- What: unnecessary preposition after a transitive verb
- Chinese-thinking cause: 「打电话**给**」「问**他**」 carry a preposition or beneficiary in Chinese; literal translation adds a stray with/to
- Fix rule: call/ask/tell/answer take a direct object; discuss takes the topic directly
- Example: "call with mom" → "**call Mom**"

### overtime-vs-over-time
- What: "overtime" (extra work hours) split into "over time"
- Chinese-thinking cause: 「加班」 is one word, so it doesn't occur to the learner that English also fuses it; "over time" means "as time passes"
- Fix rule: working late = work overtime (one word); over time = as time goes by (Things change over time)
- Example: "work over time" → "work **overtime**"

### uncountable-forced-plural
- What: forcing a plural onto an uncountable noun
- Chinese-thinking cause: Chinese 「东西」「食物」 count through context, so the translation invents a countable plural
- Fix rule: food/money/advice/information are uncountable by default; "any food/thing" is just "anything"
- Example: "any foods" → "**anything** / any food"

### of-overuse-from-de
- What: 「的」 automatically translated as "of"
- Chinese-thinking cause: in "A 的 B", "of" feels universal
- Fix rule: for relational collocations, check the fixed preposition first: tickets **for**, answer **to**, presents **for**, in the fridge
- Example: "tickets of Friday evening" → "tickets **for** Friday evening"

### capitalization-day-names
- What: days/months and other proper nouns not capitalized
- Chinese-thinking cause: Chinese has no capitalization
- Fix rule: days, months, languages, nationalities are always capitalized
- Example: "friday evening" → "**F**riday evening"

### structure-splice-leftover
- What: two candidate structures fused, leaving stray function words
- Chinese-thinking cause: during literal translation multiple English candidates coexist in the head and merge on output
- Fix rule: use one structure at a time; scan for leftover small words (of/for/to) before submitting
- Example: "one of for my mom" → "one **for** my mom"

### passive-be-plus-base-form
- What: base verb instead of past participle after "be" in a passive
- Chinese-thinking cause: in 「是……建的」 the Chinese verb doesn't inflect for passive
- Fix rule: passive = be (tensed) + past participle (built/written/delivered)
- Example: "is build" → "was **built**"

### person-plural-people
- What: plural of "person" rendered as "persons" or left unchanged
- Chinese-thinking cause: the 「人」 of 「五个人」 is identical in singular and plural
- Fix rule: everyday plural of person = people ("persons" is legal register only); number + noun as modifier is singular: a five-person team
- Example: "five person" → "five **people**"

### so-far-vs-yet
- What: "so far" misused for "not yet"
- Chinese-thinking cause: 「到现在」 translated literally; "so far" marks cumulative progress
- Fix rule: "so far" pairs with cumulative quantities (read three chapters so far); pending negatives use yet/still: hasn't arrived yet / still hasn't arrived
- Example: "hasn't arrived so far" → "**still** hasn't arrived"

### linking-verb-missing-are
- What: 「A 是给 B 的」 judgment sentence missing is/are; a noun phrase standing alone as a sentence
- Chinese-thinking cause: the 「是……的」 frame expresses judgment as a whole, so nothing feels missing
- Fix rule: an English sentence needs a conjugated verb; These presents **are** for the kids
- Example: "These presents for kids" → "These presents **are** for the kids"
