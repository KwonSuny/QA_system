# dureader_checklist 中文扩充开发诊断

原始公开标注经转换；尚未经 sunyeu 人工审核，不代表官方基准成绩。各题只在授权候选篇章内检索，无答案标签仅在该范围有效。

在同名 JSON 的 annotation_review 填写 reviewer、approved 和 notes。
确认通过后，再将逐题及整体 annotation_status 改为 human_reviewed。
同一 RGB 原题的不同变体必须留在同一划分，不能分到训练与测试两侧。

## checklist-1a9f290c86cf1e682fa6a8956d591460 · vocab

领结婚证需要户口本吗

可回答：True；参考答案：男女双方符合《婚姻法》的规定，办理结婚证需要携带的证明：1、居民身份证；2、户口簿(或者集体户籍证明)；3、婚姻状况证明。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "1a9f290c86cf1e682fa6a8956d591460", "original_type": "vocab_adj", "original_title": "领结婚证需要新户口本吗", "original_answers": [{"text": "男女双方符合《婚姻法》的规定，办理结婚证需要携带的证明：1、居民身份证；2、户口簿(或者集体户籍证明)；3、婚姻状况证明。", "answer_start": 51}], "is_impossible": false}

证据：
- dureader_checklist_2bf36834b42477df [51,112)：男女双方符合《婚姻法》的规定，办理结婚证需要携带的证明：1、居民身份证；2、户口簿(或者集体户籍证明)；3、婚姻状况证明。

### 候选资料 dureader_checklist_2bf36834b42477df

不需要，原本的户口本就可以办理结婚登记。男女双方办理结婚登记之后，可以到派出所更新户口本上的婚姻状况。男女双方符合《婚姻法》的规定，办理结婚证需要携带的证明：1、居民身份证；2、户口簿(或者集体户籍证明)；3、婚姻状况证明。

## checklist-c98573c18f943d3ccac76cb9de650ba3 · vocab

猫咪可以吃生蛋黄吗

可回答：True；参考答案：不能

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "c98573c18f943d3ccac76cb9de650ba3", "original_type": "vocab_adj", "original_title": "猫能吃蛋黄吗", "original_answers": [{"text": "不能", "answer_start": 23}], "is_impossible": false}

证据：
- dureader_checklist_ab69c698478cb744 [23,25)：不能

### 候选资料 dureader_checklist_ab69c698478cb744

猫咪是可以吃蛋黄的。这里特定煮熟的白水蛋，猫咪不能吃生鸡蛋，因为生鸡蛋中有细菌，常见的是沙门氏菌，容易引起猫腹泻脱水，而且饲喂猫咪最好的只饲喂蛋黄。虽然可以吃蛋黄，但是需要掌握好量，一般一周最多吃两三次就可了。蛋黄中也含有丰富的胆固醇，易引发猫咪患脂肪肝和高脂血病。

## checklist-e2ef75a5d2bc14e0fb68614a154655a8 · vocab

广州银行京东信用卡能提现吗

可回答：True；参考答案：京东小白卡是可以提现的。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "e2ef75a5d2bc14e0fb68614a154655a8", "original_type": "vocab_named-entity", "original_title": "京东的小白信用卡能提现吗_百度知道", "original_answers": [{"text": "京东小白卡是可以提现的。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_08b123d453d45d82 [0,12)：京东小白卡是可以提现的。

### 候选资料 dureader_checklist_08b123d453d45d82

京东小白卡是可以提现的。 可以登录京东小白卡账号,然后进行提现申请就好了,只是审核的时间是由京东来定的,所以要做好心理准备。 招商个人信用卡具备“预借现金”功能。“预借现金”是招商为信用卡持卡人提供小额现金借款,收取手续费和利息。信用卡设置交易密码,并保持预借现金功能为开通状态,方可取现。可以通过网银、手机银行和电话开通预借现金功能。

## checklist-4b4e762709c4bab1901f27cca54080bd · vocab

兰花喜欢阳光吗

可回答：True；参考答案：一般的兰花不是特别喜光，适合放在有散射光的半阴处养殖。而也有一些兰花品种，比如蕙兰，喜欢光照充足的环境，养护时需要提供给它足量的光照才能让它长好。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "4b4e762709c4bab1901f27cca54080bd", "original_type": "vocab_v", "original_title": "兰花需要阳光照吗，没有阳光能养兰花吗", "original_answers": [{"text": "一般的兰花不是特别喜光，适合放在有散射光的半阴处养殖。而也有一些兰花品种，比如蕙兰，喜欢光照充足的环境，养护时需要提供给它足量的光照才能让它长好。", "answer_start": 74}], "is_impossible": false}

证据：
- dureader_checklist_2cefccc46f2debc2 [74,147)：一般的兰花不是特别喜光，适合放在有散射光的半阴处养殖。而也有一些兰花品种，比如蕙兰，喜欢光照充足的环境，养护时需要提供给它足量的光照才能让它长好。

### 候选资料 dureader_checklist_2cefccc46f2debc2

兰花是需要阳光照射的。因为它需要通过接受阳光照射来合成养分，从而促进生长。如果长时间不受光，它就会因为缺乏养分而生长不良，出现叶片发蔫、发黑的问题。一般的兰花不是特别喜光，适合放在有散射光的半阴处养殖。而也有一些兰花品种，比如蕙兰，喜欢光照充足的环境，养护时需要提供给它足量的光照才能让它长好。

## checklist-2560b9c3431dc60f58c8f08e0dbf0c23 · vocab

狗狗为什么总是闻屁股

可回答：True；参考答案：打招呼的一种方式

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "2560b9c3431dc60f58c8f08e0dbf0c23", "original_type": "vocab_adv", "original_title": "狗狗为什么互相闻屁股", "original_answers": [{"text": "打招呼的一种方式", "answer_start": 8}], "is_impossible": false}

证据：
- dureader_checklist_c8953d5ca93d1900 [8,16)：打招呼的一种方式

### 候选资料 dureader_checklist_c8953d5ca93d1900

相互闻屁股是狗狗打招呼的一种方式。狗狗的嗅觉很敏感，它们可以用相互闻屁股来了解狗狗的配偶状况、饮食习惯等，因为狗狗的屁股后面有两个肛门腺，在肛门腺里面涵盖了很多的信息素。处在发情期的狗狗也会通过闻屁股来挑选自己的配偶。

## checklist-441b8f42cb55c1a11ade044174631ad8 · unanswerable

裤子32码是多少厘米

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "441b8f42cb55c1a11ade044174631ad8", "original_type": "vocab_units", "original_title": "裤子32码是多少尺", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_8b76b962d959a137

裤子32码对应的是二尺五，码数与尺数的计算公式为：尺数=(码数-7)/10。裤子的尺码是根据腰围、臀围、裤长等尺码数据来划分尺码大小。服装尺码标准是在人体基本尺寸的基础上，根据不同的款式，加上合适的宽松量。

## checklist-304effcfac56f488c63ec5daa504dc2f · unanswerable

西行记谁写的

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "304effcfac56f488c63ec5daa504dc2f", "original_type": "vocab_named-entity", "original_title": "", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_8089498275854c64

作者王实甫，元代著名杂剧作家，大都(今北京市)人。他一生写作了14种剧本，《西厢记》大约写于元贞、大德年间(1295～1307)是他的代表作。

## checklist-498496c1e7d819b50387f319b172d8da · unanswerable

夫妻一起借钱怎么还

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "498496c1e7d819b50387f319b172d8da", "original_type": "vocab_adv", "original_title": "夫妻单方面借钱怎么还", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_5afa078d64948adf

夫妻双方任何一方举债都会被认为是夫妻共同债务，除非共同债务人之一能拿出证据来证明借款人借款是用于个人消费，比如赌博。否则债务应有共同债务人共同偿还。

## checklist-ebbe3fc466f0f04177b8a64d2ee0de69 · unanswerable

高铁站可以充电吗

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "ebbe3fc466f0f04177b8a64d2ee0de69", "original_type": "vocab_noun", "original_title": "高铁和动车上能充电吗? - 知乎", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_253a304f8e2f4257

高铁和动车上是可以充电的,充电插头就在座位下边或者是前边。高铁动车上的充电插座排布与车型新旧有关。有些车座位是每排座位两个电源插座,有些新型车比如说“复兴号”是每两个座位有一个电源。祝旅途愉快!

## checklist-4d511014331738562409861feade97fe · unanswerable

怎么删除电脑开机密码

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "4d511014331738562409861feade97fe", "original_type": "vocab_v", "original_title": "怎么修改电脑开机密码?_酷知经验网", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_ba3b63c1aef4530a

为了电脑安全,我们会采用开机密码,那么开机密码要如何更改呢?很简单,在电脑的设置里面就能修改,设置里有个账户,账户里就可以设置密码以及更改密码,不同的操作系统大致路径也是一样的,下面小编以win10系统为例,修改电脑的开机密码。

## checklist-e0d6d467035ad9787fb46c48d0af5a70 · unanswerable

地球还能存在多少年

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "e0d6d467035ad9787fb46c48d0af5a70", "original_type": "vocab_adv", "original_title": "地球存在多久了", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_e84adfb5543b8ceb

地球已经存在45亿年的时间了，在这段时间里，地球发生了很多事情，受到了很多方面的影响，据科学家说在未来20亿年时间里人类都可以放心的居住在地球上，但5万年后地球可能会进入冰河时代，100万年后会爆发大面积火山，不过这些现在也只是猜想并不具备科学性。

## checklist-e43a7e73174b915e60bfa68e714b79ac · phrase

办护照有什么要求?

可回答：True；参考答案：需要准备材料：符合《出入境证件相片照相指引》标准的照片；居民身份证；省级公安机关出入境管理机构报经国家移民管理局批准的其他材料；未满十六周岁的，由其监护人陪同，除提交上述申请材料外，还应提交监护证明（如出生证明、户口簿等）以及监护人身份证。准备费用：护照120元/本。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "e43a7e73174b915e60bfa68e714b79ac", "original_type": "phrase", "original_title": "办护照需要准备什么？", "original_answers": [{"text": "需要准备材料：符合《出入境证件相片照相指引》标准的照片；居民身份证；省级公安机关出入境管理机构报经国家移民管理局批准的其他材料；未满十六周岁的，由其监护人陪同，除提交上述申请材料外，还应提交监护证明（如出生证明、户口簿等）以及监护人身份证。准备费用：护照120元/本。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_53c0926101790e40 [0,134)：需要准备材料：符合《出入境证件相片照相指引》标准的照片；居民身份证；省级公安机关出入境管理机构报经国家移民管理局批准的其他材料；未满十六周岁的，由其监护人陪同，除提交上述申请材料外，还应提交监护证明（如出生证明、户口簿等）以及监护人身份证。准备费用：护照120元/本。

### 候选资料 dureader_checklist_53c0926101790e40

需要准备材料：符合《出入境证件相片照相指引》标准的照片；居民身份证；省级公安机关出入境管理机构报经国家移民管理局批准的其他材料；未满十六周岁的，由其监护人陪同，除提交上述申请材料外，还应提交监护证明（如出生证明、户口簿等）以及监护人身份证。准备费用：护照120元/本。

## checklist-15d08c0ca35d728dacfafb061dfd572a · phrase

先涂精华还是乳液

可回答：True；参考答案：正常应该是在使用乳液之前使用一定的精华，不仅可以滋养肌肤还可以帮助后续护肤产品的吸收。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "15d08c0ca35d728dacfafb061dfd572a", "original_type": "phrase", "original_title": "精华在乳液前还是后", "original_answers": [{"text": "正常应该是在使用乳液之前使用一定的精华，不仅可以滋养肌肤还可以帮助后续护肤产品的吸收。", "answer_start": 39}], "is_impossible": false}

证据：
- dureader_checklist_3ab0cf0dc8a33fc8 [39,82)：正常应该是在使用乳液之前使用一定的精华，不仅可以滋养肌肤还可以帮助后续护肤产品的吸收。

### 候选资料 dureader_checklist_3ab0cf0dc8a33fc8

在乳液前。精华对于皮肤的滋养有着不错的效果，但是使用的时候也要注意掌握好步骤，正常应该是在使用乳液之前使用一定的精华，不仅可以滋养肌肤还可以帮助后续护肤产品的吸收。尤其是在冬季空气比较干燥并且比较寒冷，皮肤长时间裸露在外面，很容易导致皮肤出现缺水或者受到刺激的现象，这就需要使用一定的补水精华，让皮肤

## checklist-2ac64f7ff83158c12c541d1946173d55 · phrase

乌龟白眼病怎么治疗?

可回答：True；参考答案：补充维生素A

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "2ac64f7ff83158c12c541d1946173d55", "original_type": "phrase", "original_title": "乌龟白眼病用什么药", "original_answers": [{"text": "补充维生素A", "answer_start": 30}], "is_impossible": false}

证据：
- dureader_checklist_b69fb4651c78685d [30,36)：补充维生素A

### 候选资料 dureader_checklist_b69fb4651c78685d

因为体内维生素A缺乏导致多灶性鳞状化生和上皮细胞过度角质化。补充维生素A，可以选用含维生素A单位较高的水溶剂多维粉，一般最快两周到三周就见效，用单独水盆每日浸泡1-2小时，分两次温水浸泡，注意水量不应超过龟甲。可用抗生素眼药水清洁眼部分泌物，眼部上抗生素眼药膏，避免眼球进一步受到感染。

## checklist-37aa8bac010814ea2665191b13067c73 · phrase

地瓜和红薯一样吗

可回答：True；参考答案：地瓜不是红薯

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "37aa8bac010814ea2665191b13067c73", "original_type": "phrase", "original_title": "地瓜是红薯吗", "original_answers": [{"text": "地瓜不是红薯", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_397767571773a8fd [0,6)：地瓜不是红薯

### 候选资料 dureader_checklist_397767571773a8fd

地瓜不是红薯。地瓜一般生吃或者凉拌，外形是纺锤型的，有明显的瓣状结构，内里的肉是白色的，有清淡的药香味，生吃又脆又甜，常食用可以预防肝癌、胃癌，营养价值非常高。红薯是粗粮，也叫番薯山芋。它是一种属管状花目，旋花科一年生的草本植物，富含丰富的矿物质和维生素，而且非常耐饱。

## checklist-58b744cea6ac256703b19a633051ba79 · phrase

已满几周岁的人贩卖毒品罪应当负刑事责任

可回答：True；参考答案：十四周岁

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "58b744cea6ac256703b19a633051ba79", "original_type": "phrase", "original_title": "已满多少岁的人犯贩卖毒品罪应负刑事责任", "original_answers": [{"text": "十四周岁", "answer_start": 32}], "is_impossible": false}

证据：
- dureader_checklist_b4f5c3fc1d9dc005 [32,36)：十四周岁

### 候选资料 dureader_checklist_b4f5c3fc1d9dc005

根据《刑法》第十七条：已满十六周岁的人犯罪，应当负刑事责任。已满十四周岁不满十六周岁的人，犯故意杀人、故意伤害致人重伤或者死亡、强奸、抢劫、贩卖毒品、放火、爆炸、投放危险物质罪的，应当负刑事责任。

## checklist-6092884d20927add94c362fc6e3ab998 · unanswerable

梦见钓大鱼是什么意思

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "6092884d20927add94c362fc6e3ab998", "original_type": "phrase", "original_title": "梦见用手抓鱼是什么意思", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_d3ab820bf0bce7b9

梦见在水塘里用手抓鱼，预示着最近你会获得机遇与财富，是祥兆；梦见和别人用手抓鱼，预示着你会有意外的收获，但恋情方面有些低迷，自己要多加注意才好。梦见下雨天用手抓鱼，预示着近期你的运势很好，不论做什么事情都能够顺利。

## checklist-4b1b2b0f452096ad1f7e672bed9ae08a · unanswerable

狗吃东西吐了怎么办

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "4b1b2b0f452096ad1f7e672bed9ae08a", "original_type": "phrase", "original_title": "狗吃了一点葱怎么办", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_68fa45aeb9b84fb1

狗狗吃了葱应当立刻对它进行催吐。葱类会导致狗狗出现溶血的情况，并且很快起作用，如果没有及时催吐，狗狗后续可能会出现贫血、精神不振等非常严重的情况。催吐可以用双氧水和生理盐水进行一比一稀释进行灌食，或用肥皂水进行催吐，然后立刻带到医院交由医生救治。

## checklist-246dee97fd9a5d048c4b636f28bdce91 · unanswerable

电脑管家有必要装吗

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "246dee97fd9a5d048c4b636f28bdce91", "original_type": "phrase", "original_title": "装了电脑管家还有必要再装Mcafee吗_百度知道", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_dac833d1cbd78264

没有必要。安装两个杀毒软件可以增强电脑的安全性,但是会导致以下弊端: 占用硬盘资源过多; 在同时启用两款软件的实时防护时,会导致系统硬件资源大量损耗,例如CPU处理过多,导致计算机工作能力下降; 在进行杀毒时,会导致系统占用资源过多,不但可能影响系统工作能力,还可能误报对方组件,导致...

## checklist-862b2320b64825ec0715bc30dc31ad72 · unanswerable

狗狗可以吃牛肉吗

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "862b2320b64825ec0715bc30dc31ad72", "original_type": "phrase", "original_title": "牛肉和狗肉能一起吃吗", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_1119de44cc1dff9b

牛肉与狗肉不相冲，可以一起食用。牛肉中含有丰富的维生素、不饱和脂肪酸、胆固醇，有补血健气的功效，狗肉含有丰富的蛋白质、脂肪以及钙、磷、锌多种微量元素，两者一起食用能够均衡营养，提高身体的免疫力。

## checklist-9419d381e75ed24baa2f2ef42017afea · unanswerable

switch可以和pc联机吗

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "9419d381e75ed24baa2f2ef42017afea", "original_type": "phrase", "original_title": "switch可以联机吗", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_746a05c2ad50d436

Switch可以联机，联机分为两种，本地联机和线上联机，本地联机需要额外的手柄支持，直接绑定账号就可以联机，线上联机需要开任天堂会员，开启后就可以线上联机了。

## checklist-b78b062e4146225201007c2b66c4b214 · semantic-role

支付宝怎么换绑淘宝

可回答：True；参考答案：打开手机淘宝，在淘宝主界面选择右下方的我的淘宝，然后找到设置图标，点击进入，选择账户与安全-支付宝绑定设置选项，之后按照系统提示操作即可。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "b78b062e4146225201007c2b66c4b214", "original_type": "semantic-role", "original_title": "淘宝怎么换绑支付宝", "original_answers": [{"text": "打开手机淘宝，在淘宝主界面选择右下方的我的淘宝，然后找到设置图标，点击进入，选择账户与安全-支付宝绑定设置选项，之后按照系统提示操作即可。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_250849ecbc76ca65 [0,69)：打开手机淘宝，在淘宝主界面选择右下方的我的淘宝，然后找到设置图标，点击进入，选择账户与安全-支付宝绑定设置选项，之后按照系统提示操作即可。

### 候选资料 dureader_checklist_250849ecbc76ca65

打开手机淘宝，在淘宝主界面选择右下方的我的淘宝，然后找到设置图标，点击进入，选择账户与安全-支付宝绑定设置选项，之后按照系统提示操作即可。

## checklist-79489b00aaa04c44bb04b82bac3f3006 · semantic-role

桃子能和橙子一起吃吗

可回答：True；参考答案：能

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "79489b00aaa04c44bb04b82bac3f3006", "original_type": "semantic-role", "original_title": "橙子能和桃子一起吃吗 橙子和桃子一起吃有什么好处", "original_answers": [{"text": "能", "answer_start": 2}], "is_impossible": false}

证据：
- dureader_checklist_f7330cdc476e8dd4 [2,3)：能

### 候选资料 dureader_checklist_f7330cdc476e8dd4

橙子能和桃子一起吃。橙子性凉而味甘，富含维生素C、胡萝卜素、钙、磷等多种微量元素，而桃子性温而味甘，其中含有多种维生素、胡萝卜素、碳水化合物、钙、钾等矿物质元素，两者同食不仅没有成分上的相克反应，而且还能调节橙子寒凉的属性，对身体有诸多好处。

## checklist-9f0f9e97281fe7c83e0de9090a336d04 · semantic-role

医院和保险公司联网

可回答：True；参考答案：目前大多数的医院联网的是各地社保中的医疗保险，只有少数部分的医院和保险公司进行了联网。不过在2018年，经过银保监会的批准，首个保险＋医疗模式的医院试点正式启动，试点结束以后，保险公司将和医院进行全面联网。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "9f0f9e97281fe7c83e0de9090a336d04", "original_type": "semantic-role", "original_title": "保险公司和医院联网吗", "original_answers": [{"text": "目前大多数的医院联网的是各地社保中的医疗保险，只有少数部分的医院和保险公司进行了联网。不过在2018年，经过银保监会的批准，首个保险＋医疗模式的医院试点正式启动，试点结束以后，保险公司将和医院进行全面联网。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_82d661d18655b844 [0,103)：目前大多数的医院联网的是各地社保中的医疗保险，只有少数部分的医院和保险公司进行了联网。不过在2018年，经过银保监会的批准，首个保险＋医疗模式的医院试点正式启动，试点结束以后，保险公司将和医院进行全面联网。

### 候选资料 dureader_checklist_82d661d18655b844

目前大多数的医院联网的是各地社保中的医疗保险，只有少数部分的医院和保险公司进行了联网。不过在2018年，经过银保监会的批准，首个保险＋医疗模式的医院试点正式启动，试点结束以后，保险公司将和医院进行全面联网。

## checklist-901fbbf580b0ac26994e3ca5551be1a1 · semantic-role

朋友圈怎么发语音

可回答：True；参考答案：打开手机微信，点击我，点击收藏，点击右上角的加号，点击输入法上方的麦克风标识，说出想要发表的语音，再点击麦克风完成录制，点击右上角三个点击，选择分享到朋友圈即可。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "901fbbf580b0ac26994e3ca5551be1a1", "original_type": "semantic-role", "original_title": "语音怎么发朋友圈", "original_answers": [{"text": "打开手机微信，点击我，点击收藏，点击右上角的加号，点击输入法上方的麦克风标识，说出想要发表的语音，再点击麦克风完成录制，点击右上角三个点击，选择分享到朋友圈即可。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_f8428939956402a8 [0,81)：打开手机微信，点击我，点击收藏，点击右上角的加号，点击输入法上方的麦克风标识，说出想要发表的语音，再点击麦克风完成录制，点击右上角三个点击，选择分享到朋友圈即可。

### 候选资料 dureader_checklist_f8428939956402a8

打开手机微信，点击我，点击收藏，点击右上角的加号，点击输入法上方的麦克风标识，说出想要发表的语音，再点击麦克风完成录制，点击右上角三个点击，选择分享到朋友圈即可。

## checklist-94142f5fc9ff3bb709238a83b00b446c · semantic-role

没有欠条只有转账记录可以起诉吗

可回答：True；参考答案：根据《民事诉讼法》规定，当事人需要符合相关条件即可起诉：原告是与本案有利害关系的，有明确的被告，有具体的诉讼请求和事实理由，属于人民法院受理民事诉讼的范围和受诉人民法院管辖。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "94142f5fc9ff3bb709238a83b00b446c", "original_type": "semantic-role", "original_title": "只有欠条没有转账记录可以起诉吗", "original_answers": [{"text": "根据《民事诉讼法》规定，当事人需要符合相关条件即可起诉：原告是与本案有利害关系的，有明确的被告，有具体的诉讼请求和事实理由，属于人民法院受理民事诉讼的范围和受诉人民法院管辖。", "answer_start": 16}], "is_impossible": false}

证据：
- dureader_checklist_22afc1720e4ed179 [16,103)：根据《民事诉讼法》规定，当事人需要符合相关条件即可起诉：原告是与本案有利害关系的，有明确的被告，有具体的诉讼请求和事实理由，属于人民法院受理民事诉讼的范围和受诉人民法院管辖。

### 候选资料 dureader_checklist_22afc1720e4ed179

只有欠条没有转账记录可以起诉的。根据《民事诉讼法》规定，当事人需要符合相关条件即可起诉：原告是与本案有利害关系的，有明确的被告，有具体的诉讼请求和事实理由，属于人民法院受理民事诉讼的范围和受诉人民法院管辖。

## checklist-ac2733353672e7cc840f45795d26d564 · unanswerable

妈妈梦见女儿怀孕了

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "ac2733353672e7cc840f45795d26d564", "original_type": "semantic-role", "original_title": "女儿梦见妈妈怀孕了-易奇八字在线算命", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_2443d7b077c72266

女儿梦见妈妈怀孕了，预示着你的生活会过得很幸福，并且还会无忧无虑的生活着。

## checklist-373f6a64ef37110da447d83d76777d76 · unanswerable

女生见到暗恋男生反应

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "373f6a64ef37110da447d83d76777d76", "original_type": "semantic-role", "original_title": "男生见到暗恋女生反应", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_262230d35cb954e3

当男生见到暗恋的女生时，目光会不自觉地跟随女生移动，女生的一举一动都吸引着他。他会忍不住想和女生打招呼，以此来引起女生的注意力。另外，男生还会主动为暗恋的女生服务，比如说送她回家、为她拉椅子等，甚至对她身边的朋友也都很热情。

## checklist-793942319f1c86b95b2400166c8bd3cc · unanswerable

眼影可以当腮红用吗

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "793942319f1c86b95b2400166c8bd3cc", "original_type": "semantic-role", "original_title": "腮红可以当眼影用吗", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_25c94d6b82fe9d32

腮红可以当眼影使用。腮红的颜色一般是红或者是偏橙色，当做眼影使用的话可以选择颜色淡一些的，这样不会显得很突兀，整体效果也会很好看。所选择的腮红可以是哑光和带有一点珠光效果的，当做眼影使用比较自然。

## checklist-1de53a2056ef3b85a4eba779f99f42c3 · unanswerable

怎么把word转换成pdf

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "1de53a2056ef3b85a4eba779f99f42c3", "original_type": "semantic-role", "original_title": "怎么把pdf转换成word", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_4bba92a023f92a7b

pdf要转换成word，先双击打开“Adobe Acrobat Pro”，将软件打开后，选择想要转换成Word格式的文件，点击“打开”即可。转换成Word格式，点击“文件”项目中的“另存为”这个操作，把格式存为Word。

## checklist-15e6fcd09c3e1c37457e4df082d17527 · unanswerable

香蕉可以催熟芒果吗

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "15e6fcd09c3e1c37457e4df082d17527", "original_type": "semantic-role", "original_title": "芒果可以催熟香蕉吗", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_1b240a8e555f511e

可以。熟的芒果和香蕉放在一起，它们都会产生乙烯，而乙烯能会使生的香蕉或青的香蕉快速成熟。芒果是一种特殊水果，因为它容易成熟的特性，所以可以为其他水果起到一定催熟作用。

## checklist-0d3e3a029581d368d3e2f8e962da20ba · reasoning

晚上吃苹果不好吗

可回答：True；参考答案：苹果早晚吃没区别

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "0d3e3a029581d368d3e2f8e962da20ba", "original_type": "reasoning_negative", "original_title": "晚上吃苹果好吗", "original_answers": [{"text": "苹果早晚吃没区别", "answer_start": 62}], "is_impossible": false}

证据：
- dureader_checklist_f5947ee15ed9a79d [62,70)：苹果早晚吃没区别

### 候选资料 dureader_checklist_f5947ee15ed9a79d

首先晚上吃苹果是毒苹果的说法，是没有依据的。其次只要进食东西，肠胃就会运作，真正决定水果营养成分的是自身的身体消化能力，因此苹果早晚吃没区别。在饮食健康的基础上，每天吃个苹果，能给身体带来积极地影响。

## checklist-e2896030a34064f51ccc3e0b8e497570 · reasoning

信用卡没有逾期被冻结了还能解冻吗

可回答：True；参考答案：信用卡被冻结后是否能够解冻，具体要看和银行之间的交涉情况。持卡人和银行沟通良好，银行有可能将信用卡解冻。因为信用卡不良使用、欠款逾期等行为被银行冻结封卡的，需要持卡人本人向银行申请解冻才可以。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "e2896030a34064f51ccc3e0b8e497570", "original_type": "reasoning_negative", "original_title": "信用卡逾期被冻结了还能解冻吗", "original_answers": [{"text": "信用卡被冻结后是否能够解冻，具体要看和银行之间的交涉情况。持卡人和银行沟通良好，银行有可能将信用卡解冻。因为信用卡不良使用、欠款逾期等行为被银行冻结封卡的，需要持卡人本人向银行申请解冻才可以。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_2e705c42f6e8bc1b [0,96)：信用卡被冻结后是否能够解冻，具体要看和银行之间的交涉情况。持卡人和银行沟通良好，银行有可能将信用卡解冻。因为信用卡不良使用、欠款逾期等行为被银行冻结封卡的，需要持卡人本人向银行申请解冻才可以。

### 候选资料 dureader_checklist_2e705c42f6e8bc1b

信用卡被冻结后是否能够解冻，具体要看和银行之间的交涉情况。持卡人和银行沟通良好，银行有可能将信用卡解冻。因为信用卡不良使用、欠款逾期等行为被银行冻结封卡的，需要持卡人本人向银行申请解冻才可以。

## checklist-1ee3dcccc19539339943d93df5efda57 · reasoning

出租房隔音不好怎么解决

可回答：True；参考答案：在窗户上贴一层隔音膜

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "1ee3dcccc19539339943d93df5efda57", "original_type": "reasoning_negative", "original_title": "出租房隔音差怎么解决", "original_answers": [{"text": "在窗户上贴一层隔音膜", "answer_start": 2}], "is_impossible": false}

证据：
- dureader_checklist_8969ba24ad652f91 [2,12)：在窗户上贴一层隔音膜

### 候选资料 dureader_checklist_8969ba24ad652f91

可以在窗户上贴一层隔音膜，在粘贴过程中要注意，不要出现气泡，以免影响隔音效果。若想要隔音效果更好点，还可以购买一些密封条安装在窗户缝隙处，这也能起到更好的隔音效果。另外，室内使用的家具可以更换成木质的，这样同样能起到一定的吸音效果。

## checklist-1abc391f71732dccfa4515f8b73db172 · reasoning

最近深圳没有限行吗

可回答：True；参考答案：现在由于疫情的影响，深圳市不限行的了

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "1abc391f71732dccfa4515f8b73db172", "original_type": "reasoning_negative", "original_title": "最近深圳限行吗", "original_answers": [{"text": "现在由于疫情的影响，深圳市不限行的了", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_4c27ff086145cf5f [0,18)：现在由于疫情的影响，深圳市不限行的了

### 候选资料 dureader_checklist_4c27ff086145cf5f

现在由于疫情的影响，深圳市不限行的了，但是没有必要尽量还是少出门，出门也要做好一系列的防护措施才可以。因为虽然目前国内疫情形势有所缓和，但是这并不意味着疫情的结束，国外疫情形势还是很严峻的，境外输入案例较多。

## checklist-b08331a86006949b8cebaaa9bfd297b6 · reasoning

狗的鼻子不湿是怎么回事

可回答：True；参考答案：首先狗鼻子一般情况下是保持湿润的，在狗狗睡觉的时候狗狗的鼻子会变得干燥。如果在日常生活中发现狗狗鼻子是干燥的，就看看狗狗最近有什么异常现象，比如最近的吃喝情况有什么异常不，还有最近大小便有没有成型等等，如果还是不放心的话，就可以带到附近宠物医院，做些基本检查。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "b08331a86006949b8cebaaa9bfd297b6", "original_type": "reasoning_negative", "original_title": "狗的鼻子干是怎么回事", "original_answers": [{"text": "首先狗鼻子一般情况下是保持湿润的，在狗狗睡觉的时候狗狗的鼻子会变得干燥。如果在日常生活中发现狗狗鼻子是干燥的，就看看狗狗最近有什么异常现象，比如最近的吃喝情况有什么异常不，还有最近大小便有没有成型等等，如果还是不放心的话，就可以带到附近宠物医院，做些基本检查。", "answer_start": 0}], "is_impossible": false}

证据：
- dureader_checklist_d0f1f6dbbbd72c1e [0,130)：首先狗鼻子一般情况下是保持湿润的，在狗狗睡觉的时候狗狗的鼻子会变得干燥。如果在日常生活中发现狗狗鼻子是干燥的，就看看狗狗最近有什么异常现象，比如最近的吃喝情况有什么异常不，还有最近大小便有没有成型等等，如果还是不放心的话，就可以带到附近宠物医院，做些基本检查。

### 候选资料 dureader_checklist_d0f1f6dbbbd72c1e

首先狗鼻子一般情况下是保持湿润的，在狗狗睡觉的时候狗狗的鼻子会变得干燥。如果在日常生活中发现狗狗鼻子是干燥的，就看看狗狗最近有什么异常现象，比如最近的吃喝情况有什么异常不，还有最近大小便有没有成型等等，如果还是不放心的话，就可以带到附近宠物医院，做些基本检查。

## checklist-7722a08d7f4ca8794cc866b409462cd7 · unanswerable

什么肉蛋白质不高

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "7722a08d7f4ca8794cc866b409462cd7", "original_type": "reasoning_negative", "original_title": "什么肉蛋白质高", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_ca78f2d7d85ebd91

驴肉、鱼肉的蛋白质含量高。驴肉，是指驴的肉。“天上龙肉，地上驴肉”，是人们对驴肉的最高褒扬。每100克驴肉中含有约21.5克蛋白质，而背部肉的蛋白质含量高达21.6%。而鱼肉也含有大量的蛋白质，如黄鱼含17.6%、带鱼含18.1%、鲐鱼含21.4%、鲢鱼含18.6%。

## checklist-183b9b71952bd2f0b8401249ab2b3960 · unanswerable

梦见救落水小孩不成功

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "183b9b71952bd2f0b8401249ab2b3960", "original_type": "reasoning_negative", "original_title": "梦见梦见救落水小孩成功", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_524cd8a4cf127d26

单身女人得此梦者多主，你的感情会受影响，而你渴望能够得到真正适合你的人，则你在感情中已经期待了许久，而你渴望在爱情中能有好的际遇，这你就更应该把握当下感情与别人交涉的机会。

## checklist-e82247884b62c7f42541ed06155ebf82 · unanswerable

什么猫最不粘人

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "e82247884b62c7f42541ed06155ebf82", "original_type": "reasoning_negative", "original_title": "什么猫最粘人", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_3d9fc2437d964c20

都说猫高冷，其实猫里面也有不高冷的，下面就是几种非常黏人的猫布偶猫谈到布偶猫就不得不说宝宝的颜值，眼睛大大的圆溜溜的，时不时还发出迷离的小眼神，四肢较长很有肉感，身体也很柔软，布偶猫较为温顺好静，生气的时候很少见，对人非常友善。温顺的性格和美丽的外表，又被称

## checklist-f42c9e6d6b7e375f67bb684e097e754d · unanswerable

做梦梦见自己没有结婚

可回答：False；参考答案：资料不足，应拒答。

原始标注：{"dataset": "dureader_checklist", "original_split": "dev", "original_id": "f42c9e6d6b7e375f67bb684e097e754d", "original_type": "reasoning_negative", "original_title": "做梦梦见自己结婚", "original_answers": [{"text": "", "answer_start": -1}], "is_impossible": true}

证据：
- 无答案证据；需核对下列全部候选资料是否确实不足。

### 候选资料 dureader_checklist_8e766c90243298b4

做梦梦见自己结婚，内心自卑，说话伤人。计划出行的人做梦梦见自己结婚，行程延误。考生做梦梦见自己结婚，成绩不好。创业者做梦梦见自己结婚，凡事谨慎为好。谈婚论嫁的人做梦梦见自己结婚，婚姻顺利。已婚男女做梦梦见自己结婚，对现状不满。
