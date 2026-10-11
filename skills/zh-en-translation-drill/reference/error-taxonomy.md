# 错误模式分类表

中译英错误标签字典。每个标签 5 字段：是什么 / 中文成因 / 修正规则 / 例句。批改时优先用已有标签；没有匹配的造新标签追加到本文件末尾。标签用 kebab-case。

---

## 冠词

### article-missing-a
- 是什么：单数可数名词前漏 a/an
- 中文成因：中文没有冠词系统
- 修正规则：单数可数名词几乎必须有 a/an/the；首次引入新事物默认 a/an
- 例句："I have cat" → "I have **a** cat"

### article-missing-the
- 是什么：双方已知的事物前漏 the
- 中文成因：「那个」在中文里可省，英文 the 不可省
- 修正规则：说话双方都知道指哪个时用 the
- 例句："I fixed bug in login page" → "I fixed **the** bug on the login page"

### article-overuse-the
- 是什么：泛指概念滥用 the
- 中文成因：「的」字结构让人感觉需要限定词
- 修正规则：泛指复数或不可数名词不加 the
- 例句："the society needs the trust" → "society needs trust"

## 名词与数

### plural-missing-s
- 是什么：可数名词复数漏 -s
- 中文成因：中文复数靠语境，不变形
- 修正规则：多于一个就必须 -s
- 例句："three customer" → "three customers"

## 动词

### verb-tense-flat
- 是什么：该用过去式的地方用现在式
- 中文成因：中文靠「昨天」等时间词，动词不变形
- 修正规则：动作发生在过去且完成 → 过去式。时间词不能替代变形
- 例句："yesterday I go to the meeting" → "yesterday I **went** to the meeting"

### third-person-s
- 是什么：三单现在时漏 -s
- 中文成因：动词不随人称变化
- 修正规则：he/she/it + 动词 → 动词加 -s
- 例句："he run fast" → "he run**s** fast"

### to-plus-ing
- 是什么：不定式 to 后接了 -ing
- 中文成因：把「去做某事」和「在做某事」混同
- 修正规则：不定式 to + 动词原形
- 例句："help me to refactoring" → "help me **refactor**"

### passive-avoided
- 是什么：该用被动的地方硬凑主动句
- 中文成因：「被」字句在中文里常带负面色彩，能避则避
- 修正规则：施动者不重要或不明确时，英文偏好被动或物称主语
- 例句："People widely use this method" → "This method **is widely used**"

## 句子结构

### pronoun-it-missing
- 是什么：漏掉形式主语 it
- 中文成因：中文可以无主语
- 修正规则：英文句子必须有主语，天气/时间/评价用 it
- 例句："is raining" → "**It**'s raining"

### embedded-question-word-order
- 是什么：宾语从句用了疑问语序
- 中文成因：中文疑问和陈述同序
- 修正规则：疑问句嵌进句子后回到陈述语序
- 例句："I need to know what's that mean" → "I need to know what that **means**"

### run-on-comma-splice
- 是什么：逗号连接两个完整句（中式流水句直译）
- 中文成因：中文逗号可以一路连下去
- 修正规则：英文两个独立句之间用句号/分号/连词，不能裸逗号
- 例句："It was raining, I stayed home" → "It was raining, **so** I stayed home."

### subject-swallow
- 是什么：无主语直译（中文主语省略后英文也省）
- 中文成因：中文话题链里主语频繁省略
- 修正规则：英文每个分句都要有显式主语
- 例句："Learned a lot from this project" → "**I** learned a lot from this project"

### because-so-double
- 是什么：because 和 so 连用
- 中文成因：「因为……所以……」成对出现
- 修正规则：英文因果连词只取一个
- 例句："Because it rained, so we cancelled" → "Because it rained, we cancelled"

### word-order-adjective-after-noun
- 是什么：定语位置错误或定语从句乱序
- 中文成因：中文定语一律前置，长定语直译后头重脚轻
- 修正规则：英文长修饰后置（介词短语/从句），短形容词前置
- 例句："the people who work in this field" ≠ "this field's work people"

## 用词

### collocation-wrong-partner
- 是什么：语法对但搭配错
- 中文成因：中文动宾搭配逐字直译
- 修正规则：查母语者固定搭配，搭配是死的
- 例句："do research" → "**conduct** research"；"big growth" → "**significant** growth"

### literal-translation-chinglish
- 是什么：逐字直译产出不存在于英文的表达
- 中文成因：字字对应翻译习惯
- 修正规则：先问「母语者表达这个意思用什么」，再问「字面怎么译」
- 例句："People mountain people sea" → "huge crowds"；"add oil" → "keep going / you got it"

### register-mismatch
- 是什么：语域错位（口语句用在书面 / 反之）
- 中文成因：中文书面口语分界与英文不同，且中文译不出正式度差异
- 修正规则：先判断场景（邮件/论文/聊天），选对应语域
- 例句：正式邮件里 "I wanna know" → "I would like to know"

### preposition-about-vs-with
- 是什么：with/about 混用
- 中文成因：「跟」同时映射 with 和 about
- 修正规则：with = 交流对象，about = 话题
- 例句："talk with that" → "talk **about** that"

## 拼写与易混词

### spelling-typo
- 是什么：单词拼写手滑
- 中文成因：无（输入错误）
- 修正规则：交卷前扫一遍每个动词的拼写
- 例句："wachted" → "**watched**"

### rest-vs-reset
- 是什么：rest（休息）与 reset（重置）混用
- 中文成因：发音相近脑补；reset 是重置密码的重置
- 修正规则：休息 = rest；重置设备/密码 = reset
- 例句："take a reset" → "take a **rest**"

## 时间与频率

### time-adverbial-order
- 是什么：时间状语顺序生硬或拆散
- 中文成因：把「昨天下午」这类时间词拆开逐个译
- 修正规则：英文固定时间短语直接连写：yesterday afternoon / last Friday evening
- 例句："in the afternoon yesterday" → "**yesterday afternoon**"

### everyday-vs-every-day
- 是什么：everyday（形容词「日常的」）与 every day（副词「每天」）混用
- 中文成因：「每天」逐字译成 everyday 一个词
- 修正规则：作状语用 every day 两个词；everyday 只作定语（everyday life）。「每天早上」= every morning
- 例句："everday morning" → "**every morning**"

## 名词与数

### there-be-agreement-nearest
- 是什么：there be 后并列一单一复时动词用错
- 中文成因：中文「有」不随数变形；就近一致是英文特有规则
- 修正规则：动词与最近名词一致；口语单数开头直接 There's
- 例句："There are an apple and two oranges" → "**There's an apple** and two oranges"

### source-misread
- 是什么：看串原文数量/细节
- 中文成因：无（阅读疏漏）
- 修正规则：动笔前把原文里的数字圈出来
- 例句：两个橘子译成 "three oranges" → "**two** oranges"

## 动词

### modal-plus-past-form
- 是什么：情态动词后接了过去式
- 中文成因：「能到」的「到」不变形，英文 can 后必须原形
- 修正规则：can/could/will/must + 动词原形
- 例句："I can arrived" → "I can **get/arrive**"

### modal-mixed-structure
- 是什么：两个结构硬拼（can + be free to）
- 中文成因：逐字翻译时把多个候选结构揉在一起
- 修正规则：一次只用一个结构：can + 原形 或 be free to + 动词；邀请语直接用 help yourself
- 例句："you can free to taste" → "**help yourself**"

### infinitive-after-want
- 是什么：want/need/hope 后接了 -ing
- 中文成因：「想做」的「做」不变形
- 修正规则：want/need/hope/decide + to do
- 例句："I want taking" → "I want **to take**"

### intransitive-verb-object
- 是什么：不及物动词后直接带宾语
- 中文成因：「到了它」直译；arrive 不及物
- 修正规则：arrive at + 地点，或换 get there
- 例句："arrived it" → "**get there** / arrive **at** it"

## 句子结构

### distance-close-structure
- 是什么：「A 离 B 很近」句型直译失败（this 脑补主语 + between 误用）
- 中文成因：中文主语可省略；「离」被映射成 between
- 修正规则：A is close to B；或 I live close to / a ten-minute walk from B
- 例句："this's close between my home and company" → "**My home is close to the office**"

---

## 新标签模板

```
### new-label-name
- 是什么：……
- 中文成因：……
- 修正规则：……
- 例句："……" → "……"
```

### finite-verb-missing-ing
- 是什么：用 -ing 形式当谓语，句子没有变位的主干动词
- 中文成因：中文动词无形态变化，「跑步」本身既是原形也是完整谓语，直译成 running 以为句子已完整
- 修正规则：一般现在时陈述句必须有变位动词（三单加 -s）；-ing 只能跟在 be / go 等动词后面
- 例句："My sister running every evening" → "My sister **runs** every evening"

### progressive-for-habitual
- 是什么：长期职业/习惯状态用了进行时
- 中文成因：「在……工作」的「在」是地点/状态标记，被当成进行时的"正在"
- 修正规则：长期状态 → 一般现在时；进行时只用于此刻/临时动作（He's working from home today）
- 例句："His brother is working at a hospital" → "His brother **works** at a hospital"

### base-form-after-aux
- 是什么：助动词后主动词保留变位/未还原原形
- 中文成因：中文否定只加「不」，动词不动；英文把变位搬到助动词 does 上，主动词必须还原，学习者两边各变一半
- 修正规则：变位只出现一次，且只在助动词上：doesn't/don't/can/will + 动词原形
- 例句："don't works" → "doesn't **work**"

### habitual-time-noun-plural
- 是什么：习惯性时间名词漏复数
- 中文成因：中文「周末」「工作日」无单复数之分
- 修正规则：表「每逢」的习惯性时间用复数：on weekends / on weekdays
- 例句："on weekend" → "on weekend**s**"

### transitive-verb-extra-prep
- 是什么：及物动词后加了多余介词
- 中文成因：「打电话**给**」「问**他**」中文带介词或受益对象，逐字直译多出 with/to
- 修正规则：call/ask/tell/answer 直接接宾语；discuss 直接接话题
- 例句："call with mom" → "**call Mom**"

### overtime-vs-over-time
- 是什么：加班 overtime 拆写成 over time
- 中文成因：「加班」一个词，映射时想不到英文也是合成一个词；over time 意思是「随着时间推移」
- 修正规则：加班 = work overtime（一个词）；over time = 随时间流逝（Things change over time）
- 例句："work over time" → "work **overtime**"

### uncountable-forced-plural
- 是什么：不可数名词强行加复数
- 中文成因：中文「东西」「食物」靠语境计数，映射时脑补可数复数
- 修正规则：food/money/advice/information 默认不可数；「任何食物/东西」直接用 anything
- 例句："any foods" → "**anything** / any food"

### of-overuse-from-de
- 是什么：中文「的」一律直译成 of
- 中文成因：「A 的 B」结构里 of 感觉万能
- 修正规则：关系类搭配优先查固定介词：tickets **for**、answer **to**、presents **for**、in the fridge
- 例句："tickets of Friday evening" → "tickets **for** Friday evening"

### capitalization-day-names
- 是什么：星期/月份等专有名词未大写
- 中文成因：中文没有大写概念
- 修正规则：星期、月份、语言、国籍首字母永远大写
- 例句："friday evening" → "**F**riday evening"

### structure-splice-leftover
- 是什么：两个候选结构揉在一起，残留多余虚词
- 中文成因：逐字翻译时脑内多个英文候选并存，输出时合并
- 修正规则：一次只用一个结构；交卷前扫残留小词（of/for/to）
- 例句："one of for my mom" → "one **for** my mom"

### passive-be-plus-base-form
- 是什么：被动句 be 后接动词原形而非过去分词
- 中文成因：「是……建的」被动在中文里动词不变形
- 修正规则：被动 = be（按时态）+ 过去分词（built/written/delivered）
- 例句："is build" → "was **built**"

### person-plural-people
- 是什么：person 复数误作 persons 或不变形
- 中文成因：「五个人」的「人」单复数同形
- 修正规则：日常语境 person 复数 = people（persons 仅法律文书）；数字+名词做定语时反而单数：a five-person team
- 例句："five person" → "five **people**"

### so-far-vs-yet
- 是什么：「到现在还没」误用 so far
- 中文成因：「到现在」直译；so far 是累计进度标记
- 修正规则：so far 配累计量（read three chapters so far）；等待中的否定用 yet/still：hasn't arrived yet / still hasn't arrived
- 例句："hasn't arrived so far" → "**still** hasn't arrived"

### linking-verb-missing-are
- 是什么：「A 是给 B 的」判断句漏掉 are/is，名词短语直接当句子
- 中文成因：「是……的」结构整体表判断，感觉不缺成分
- 修正规则：英文句子必须有变位动词；These presents **are** for the kids
- 例句："These presents for kids" → "These presents **are** for the kids"
