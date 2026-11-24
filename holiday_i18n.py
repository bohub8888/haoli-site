#!/usr/bin/env python3
"""节假日名称的中文化：国家清单 + 英文名 → 中文名。

数据由 holidays（vacanza/holidays）库提供，因库内名称随国家语言不同，
统一取 language="en_US" 再用本文件的词典译为中文，未命中时按规则降级。

为什么单独一个文件：词典是这个项目里最需要长期维护的部分，
和构建逻辑放一起会互相淹没；以后加国家只需在这里加一行 + 几条译名。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 国家清单
# (ISO 代码, 文件名前缀, 中文名, 地区, 卡片说明)
# 中国内地、中国香港、中国澳门、中国台湾不用这个表，走各自的数据源。

COUNTRIES: list[tuple[str, str, str, str, str]] = [
    ("JP", "jp", "日本", "东亚", "祝日与振替休日"),
    ("KR", "korea", "韩国", "东亚", "公休日与补假"),
    ("MN", "mn", "蒙古", "东亚", "公共假日"),

    ("SG", "sg", "新加坡", "东南亚", "公共假日"),
    ("MY", "my", "马来西亚", "东南亚", "公共假日"),
    ("TH", "th", "泰国", "东南亚", "佛教节日与公休"),
    ("VN", "vn", "越南", "东南亚", "公共假日"),
    ("ID", "id", "印度尼西亚", "东南亚", "公共假日"),
    ("PH", "ph", "菲律宾", "东南亚", "法定与特别假日"),
    ("KH", "kh", "柬埔寨", "东南亚", "公共假日"),
    ("LA", "la", "老挝", "东南亚", "公共假日"),
    ("MM", "mm", "缅甸", "东南亚", "公共假日"),
    ("BN", "bn", "文莱", "东南亚", "公共假日"),

    ("IN", "india", "印度", "南亚", "联邦与主要节日"),
    ("PK", "pk", "巴基斯坦", "南亚", "公共假日"),
    ("BD", "bd", "孟加拉国", "南亚", "公共假日"),
    ("NP", "np", "尼泊尔", "南亚", "公共假日"),
    ("KZ", "kz", "哈萨克斯坦", "中亚", "公共假日"),

    ("AE", "ae", "阿联酋", "中东", "公共假日"),
    ("SA", "sa", "沙特阿拉伯", "中东", "公共假日"),
    ("QA", "qa", "卡塔尔", "中东", "公共假日"),
    ("KW", "kw", "科威特", "中东", "公共假日"),
    ("IL", "il", "以色列", "中东", "犹太节日"),
    ("TR", "tr", "土耳其", "中东", "公共假日"),

    ("GB", "uk", "英国", "欧洲", "银行假日"),
    ("DE", "de", "德国", "欧洲", "联邦法定假日"),
    ("FR", "fr", "法国", "欧洲", "公共假日"),
    ("IT", "it", "意大利", "欧洲", "公共假日"),
    ("ES", "es", "西班牙", "欧洲", "公共假日"),
    ("PT", "pt", "葡萄牙", "欧洲", "公共假日"),
    ("NL", "nl", "荷兰", "欧洲", "公共假日"),
    ("BE", "be", "比利时", "欧洲", "公共假日"),
    ("CH", "ch", "瑞士", "欧洲", "联邦法定假日"),
    ("AT", "at", "奥地利", "欧洲", "公共假日"),
    ("SE", "se", "瑞典", "欧洲", "公共假日"),
    ("NO", "no", "挪威", "欧洲", "公共假日"),
    ("DK", "dk", "丹麦", "欧洲", "公共假日"),
    ("FI", "fi", "芬兰", "欧洲", "公共假日"),
    ("IS", "is", "冰岛", "欧洲", "公共假日"),
    ("IE", "ie", "爱尔兰", "欧洲", "公共假日"),
    ("PL", "pl", "波兰", "欧洲", "公共假日"),
    ("CZ", "cz", "捷克", "欧洲", "公共假日"),
    ("SK", "sk", "斯洛伐克", "欧洲", "公共假日"),
    ("HU", "hu", "匈牙利", "欧洲", "公共假日"),
    ("RO", "ro", "罗马尼亚", "欧洲", "公共假日"),
    ("GR", "gr", "希腊", "欧洲", "公共假日"),
    ("RU", "ru", "俄罗斯", "欧洲", "公共假日"),

    ("US", "us", "美国", "北美", "联邦假日"),
    ("CA", "canada", "加拿大", "北美", "联邦法定假日"),
    ("MX", "mx", "墨西哥", "北美", "法定假日"),

    ("BR", "br", "巴西", "南美", "公共假日"),
    ("AR", "ar", "阿根廷", "南美", "公共假日"),
    ("CL", "cl", "智利", "南美", "公共假日"),
    ("CO", "co", "哥伦比亚", "南美", "公共假日"),
    ("PE", "pe", "秘鲁", "南美", "公共假日"),

    ("AU", "au", "澳大利亚", "大洋洲", "公共假日"),
    ("NZ", "nz", "新西兰", "大洋洲", "公共假日"),

    ("EG", "eg", "埃及", "非洲", "公共假日"),
    ("ZA", "za", "南非", "非洲", "公共假日"),
    ("MA", "ma", "摩洛哥", "非洲", "公共假日"),
    ("KE", "ke", "肯尼亚", "非洲", "公共假日"),
    ("NG", "ng", "尼日利亚", "非洲", "公共假日"),
]

# 地区 → 合集文件名前缀（用于「亚洲合集」这类打包下载）
REGION_SLUG = {
    "东亚": "east-asia",
    "东南亚": "southeast",
    "南亚": "south-asia",
    "中亚": "central-asia",
    "中东": "middle-east",
    "欧洲": "europe",
    "北美": "north-america",
    "南美": "south-america",
    "大洋洲": "oceania",
    "非洲": "africa",
}

REGION_NOTE = {
    "东亚": "中 · 日 · 韩 · 蒙",
    "东南亚": "新马泰越印尼菲柬老缅文莱",
    "南亚": "印巴孟尼",
    "中亚": "哈萨克斯坦",
    "中东": "海湾六国 · 以色列 · 土耳其",
    "欧洲": "欧盟主要国家 + 英国 · 瑞士 · 俄罗斯",
    "北美": "美 · 加 · 墨",
    "南美": "巴西 · 阿根廷 · 智利 · 哥伦比亚 · 秘鲁",
    "大洋洲": "澳 · 新",
    "非洲": "埃及 · 南非 · 摩洛哥 · 肯尼亚 · 尼日利亚",
}

# ---------------------------------------------------------------- 译名词典

ZH: dict[str, str] = {
    # 全球通用
    "New Year's Day": "元旦",
    "New Year's Eve": "跨年夜",
    "New Year Holidays": "元旦假期",
    "International New Year Day": "元旦",
    "Day after New Year's Day": "元旦次日",
    "Chinese New Year": "春节",
    "Chinese New Year's Day": "春节",
    "Lunar New Year": "农历新年",
    "Lunar New Year's Eve": "除夕",
    "Spring Festival": "春节",
    "Christmas Day": "圣诞节",
    "Christmas": "圣诞节",
    "Christmas Eve": "平安夜",
    "Second Day of Christmas": "圣诞节次日",
    "Boxing Day": "节礼日",
    "Good Friday": "耶稣受难日",
    "Holy Saturday": "圣周六",
    "Easter": "复活节",
    "Easter Sunday": "复活节",
    "Easter Monday": "复活节星期一",
    "Ascension Day": "耶稣升天节",
    "Pentecost": "圣灵降临节",
    "Pentecost Monday": "圣灵降临节星期一",
    "Maundy Thursday": "濯足节",
    "All Saints' Day": "诸圣节",
    "All Souls' Day": "万灵节",
    "Immaculate Conception": "圣母无原罪日",
    "Assumption Day": "圣母升天节",
    "Assumption Of Mary Day": "圣母升天节",
    "Corpus Christi": "基督圣体节",
    "Epiphany": "主显节",
    "Sacred Heart": "耶稣圣心节",
    "Trinity Sunday": "三一主日",
    "Reformation Day": "宗教改革日",
    "Orthodox Christmas": "东正教圣诞节",
    "Orthodox Christmas Day": "东正教圣诞节",
    "Coptic Christmas Day": "科普特圣诞节",
    "Saint Stephen's Day": "圣斯德望日",
    "Saint John the Baptist": "施洗约翰节",
    "Saint Peter and Saint Paul's Day": "圣彼得与圣保罗日",
    "Saints Cyril and Methodius Day": "圣西里尔与美多德日",
    "Saint Joseph's Day": "圣若瑟日",
    "Saint Patrick's Day": "圣帕特里克节",
    "Saint Andrew's Day": "圣安德鲁日",
    "Saint Brigid's Day": "圣布里吉德日",
    "Saint George's Day": "圣乔治日",
    "Dormition of the Mother of God": "圣母安息节",
    "Glorifying Mother of God": "圣母荣耀节",
    "Day of Our Lady of the Seven Sorrows": "圣母七苦日",
    "Our Lady of Aparecida": "阿帕雷西达圣母日",
    "Our Lady of Mount Carmel": "加尔默罗山圣母日",
    "Rose of Lima Day": "利马玫瑰圣母日",
    "Saint Francis of Assisi, Patron Saint of Italy": "圣方济各日（意大利主保）",

    "Labor Day": "劳动节",
    "Labour Day": "劳动节",
    "Labor Day (observed)": "劳动节（补假）",
    "National Labor Day": "劳动节",
    "International Labor Day": "国际劳动节",
    "Workers' Day": "劳动者节",
    "Worker's Day": "劳动者节",
    "May Day": "五一节",
    "Holiday of Spring and Labor": "春季劳动节",
    "Labor and Solidarity Day": "劳动与团结日",
    "Labor Thanksgiving Day": "勤劳感谢日",

    "National Day": "国庆节",
    "National Day Holiday": "国庆假期",
    "National Holiday": "公共假日",
    "Independence Day": "独立日",
    "National Independence Day": "国家独立日",
    "National Freedom and Independence Day": "自由独立日",
    "Restoration of Independence Day": "独立恢复日",
    "Proclamation of Independence Day": "独立宣言日",
    "Constitution Day": "宪法日",
    "Republic Day": "共和国日",
    "Republic Proclamation Day": "共和国宣言日",
    "Victory Day": "胜利日",
    "Liberation Day": "解放日",
    "Liberation Day/Reunification Day": "解放日暨统一日",
    "Revolution Day": "革命日",
    "Democracy Day": "民主日",
    "Memorial Day": "阵亡将士纪念日",
    "Veterans Day": "退伍军人节",
    "Remembrance Day": "国殇纪念日",
    "Armistice Day": "停战纪念日",
    "Unity Day": "统一日",
    "National Unity Day": "民族团结日",
    "Statehood Day": "建州日",
    "Foundation Day": "建国日",
    "Founding Day Holiday": "建国日假期",
    "State Foundation Day": "建国日",
    "Heritage Day": "遗产日",
    "Family Day": "家庭日",
    "Youth Day": "青年节",
    "Children's Day": "儿童节",
    "National Children's Day": "儿童节",
    "National Women's Day": "妇女节",
    "International Women's Day": "国际妇女节",
    "International Women's Rights Day": "国际妇女权利日",
    "National Sports Day": "体育日",
    "Sports Day": "体育日",
    "Human Rights Day": "人权日",
    "Freedom Day": "自由日",
    "Day of Goodwill": "善意日",
    "Day of Reconciliation": "和解日",
    "Day of Silence": "静默日",
    "Day of Valor": "勇气日",
    "Armed Forces Day": "建军节",
    "Army Day": "陆军节",
    "Navy Day": "海军节",
    "Air Force Day": "空军节",
    "Memorial Day of the Fallen": "烈士纪念日",
    "Martyrs' Day": "烈士日",
    "Martyr's Day": "烈士日",
    "National Heroes Day": "国家英雄日",
    "Peasants' Day": "农民节",
    "Capital Day": "首都日",
    "Commerce Day": "商业日",
    "Coronation Day": "加冕日",
    "Throne Day": "登基日",
    "King's Day": "国王日",
    "King's Birthday": "国王诞辰",
    "Emperor's Birthday": "天皇诞辰",
    "Green March": "绿色进军纪念日",
    "Green Monday": "绿色星期一",
    "Greenery Day": "绿之日",
    "Showa Day": "昭和日",
    "Culture Day": "文化日",
    "Marine Day": "海之日",
    "Mountain Day": "山之日",
    "Coming of Age Day": "成人日",
    "Respect for the Aged Day": "敬老日",
    "Autumnal Equinox Day": "秋分日",
    "Vernal Equinox Day": "春分日",
    "First Day of Summer": "入夏节",
    "Midsummer Day": "仲夏节",
    "Midsummer Eve": "仲夏前夜",
    "Thanksgiving Day": "感恩节",
    "Columbus Day": "哥伦布日",
    "Veterans Day": "退伍军人节",
    "Presidential Inauguration Day": "总统就职日",
    "Washington's Birthday": "华盛顿诞辰",
    "Martin Luther King Jr. Day": "马丁·路德·金日",
    "Juneteenth National Independence Day": "六月节",
    "National Indigenous Peoples Day": "原住民日",
    "Canada Day": "加拿大国庆日",
    "Australia Day": "澳大利亚国庆日",
    "ANZAC Day": "澳新军团日",
    "Anzac Day": "澳新军团日",
    "Waitangi Day": "怀唐伊日",
    "Matariki": "毛利新年",

    # 伊斯兰 / 印度 / 犹太 / 东南亚宗教节日
    "Eid al-Fitr": "开斋节",
    "Eid al-Fitr Holiday": "开斋节假期",
    "Eid al-Fitr (Second Day)": "开斋节第二天",
    "Eid al-Fitr Second Day": "开斋节第二天",
    "Eid al-Adha": "宰牲节",
    "Eid al-Adha Holiday": "宰牲节假期",
    "Islamic New Year": "伊斯兰新年",
    "Prophet's Birthday": "先知诞辰",
    "Prophet Muhammad's Birthday": "先知穆罕默德诞辰",
    "Isra' and Mi'raj": "登霄节",
    "Ashura": "阿舒拉节",
    "Day of Arafah": "阿拉法特日",
    "Laylat al-Qadr": "盖德尔夜",
    "Mid-Sha'ban": "舍尔邦月中",
    "Jumu'atul-Wida": "斋月最后一个主麻日",
    "First Day of Ramadan": "斋月开始",
    "Anniversary of the revelation of the Quran": "古兰经降示纪念日",
    "Nowruz Holiday": "诺鲁孜节",
    "Diwali": "排灯节",
    "Holi": "洒红节",
    "Dussehra": "十胜节",
    "Maha Shivaratri": "湿婆节",
    "Ram Navami": "罗摩诞辰",
    "Janmashtami (Vaishnava)": "黑天诞辰",
    "Shree Krishna Janmashtami": "黑天诞辰",
    "Mahavira's Birthday": "大雄诞辰",
    "Guru Nanak's Birthday": "那纳克诞辰",
    "Buddha Purnima": "佛诞节",
    "Buddha Jayanti": "佛诞节",
    "Buddha's Birthday": "佛诞节",
    "The Buddha's Birthday": "佛诞节",
    "Vesak Day": "卫塞节",
    "Visakha Bucha": "卫塞节",
    "Visaka Bochea Day": "卫塞节",
    "Makha Bucha": "万佛节",
    "Asarnha Bucha": "三宝佛节",
    "Buddhist Lent Day": "入夏节",
    "Songkran Festival": "宋干节（泼水节）",
    "Water Festival": "送水节",
    "Pchum Ben Day": "亡人节",
    "Khmer New Year's Day": "高棉新年",
    "Lao New Year's Day": "老挝新年",
    "Myanmar New Year": "缅甸新年",
    "Bengali New Year's Day": "孟加拉新年",
    "Nepali New Year": "尼泊尔新年",
    "Karen New Year": "克伦新年",
    "Tamu Lhochhar": "古隆新年",
    "Gyalpo Lhosar; Sonam Lhochhar": "藏历新年",
    "Amazigh New Year": "柏柏尔新年",
    "Rosh Hashanah": "犹太新年",
    "Yom Kippur": "赎罪日",
    "Pesach": "逾越节",
    "Seventh day of Pesach": "逾越节第七日",
    "Shavuot": "五旬节（犹太）",
    "Sukkot": "住棚节",
    "Simchat Torah / Shemini Atzeret": "妥拉节",
    "Purim": "普珥节",
    "Hanukkah": "光明节",
    "Passover": "逾越节",

    # 南亚细节
    "Maha Ashtami": "十胜节第八日",
    "Maha Navami": "十胜节第九日",
    "Bijaya Dashami": "十胜节第十日",
    "Ekadashi (Dashain)": "十胜节第十一日",
    "Duwadashi (Dashain)": "十胜节第十二日",
    "Ghatasthapana": "圣罐安置日",
    "Fulpati": "富尔帕蒂日",
    "Chhath Parva": "太阳神节",
    "Maghe Sankranti": "玛格月节",
    "Prithvi Jayanti": "普里特维诞辰",
    "Bhai Tika": "兄弟姐妹节",
    "Gai Tihar; Laxmi Pooja": "灯节 / 财神日",
    "Gobardhan Pooja; Mha Pooja": "牛节 / 自敬日",
    "Fagu Poornima": "洒红节",
    "Fagu Poornima (Terai)": "洒红节（特莱地区）",
    "Janai Poornima": "圣线节",
    "Dr. B. R. Ambedkar's Birthday": "安贝德卡诞辰",
    "Mahatma Gandhi's Birthday": "甘地诞辰",
    "Kashmir Solidarity Day": "克什米尔团结日",
    "Pakistan Day": "巴基斯坦日",
    "Iqbal Day": "伊克巴尔日",
    "Quaid-e-Azam Day": "真纳诞辰",
    "Youm-e-Takbeer": "伟大日",
    "Martyrs' Day and International Mother Language Day": "烈士日暨国际母语日",

    # 日本 / 韩国
    "Hangul Day": "韩文日",
    "Chuseok": "秋夕",
    "Korean New Year": "韩国新年",
    "The day preceding Chuseok": "秋夕前一日",
    "The second day of Chuseok": "秋夕第二天",
    "The day preceding Korean New Year": "韩国新年前一日",
    "The second day of Korean New Year": "韩国新年第二天",
    "Independence Movement Day": "三一节",
    "National Foundation Day": "开天节",
    "Liberation Day": "光复节",

    # 泰国 / 柬埔寨 / 文莱等王室相关
    "Chakri Memorial Day": "却克里王朝纪念日",
    "Royal Ploughing Ceremony": "御耕节",
    "HM King Bhumibol Adulyadej Memorial Day": "普密蓬国王纪念日",
    "HM King Bhumibol Adulyadej the Great's Birthday; National Day; National Father's Day": "普密蓬国王诞辰暨国庆、父亲节",
    "HM King Maha Vajiralongkorn's Birthday": "哇集拉隆功国王诞辰",
    "HM Queen Suthida's Birthday": "素提达王后诞辰",
    "HM Queen Sirikit The Queen Mother's Birthday; National Mother's Day": "诗丽吉太后诞辰暨母亲节",
    "HM King Chulalongkorn Memorial Day": "朱拉隆功国王纪念日",
    "HM King Norodom Sihamoni's Birthday": "西哈莫尼国王诞辰",
    "HM King Norodom Sihamoni's Coronation Day": "西哈莫尼国王加冕日",
    "HM King Norodom Sihanouk Mourning Day": "西哈努克国王逝世纪念日",
    "HM Queen Norodom Monineath Sihanouk the Queen-Mother's Birthday": "莫尼列太后诞辰",
    "Birthday of HM Yang di-Pertuan Agong": "最高元首诞辰",
    "Sultan Hassanal Bolkiah's Birthday": "哈桑纳尔·博尔基亚苏丹诞辰",
    "Peace Day in Cambodia": "柬埔寨和平日",
    "Great Military Parade Day": "大阅兵日",
    "Genghis Khan's Birthday": "成吉思汗诞辰",
    "Kazakhstan's People Solidarity Holiday": "哈萨克斯坦民族团结日",
    "Qatar National Day": "卡塔尔国庆日",
    "Malaysia Day": "马来西亚日",
    "Lao National Day": "老挝国庆日",
    "Vietnam Cultural Day": "越南文化日",
    "Hung Kings' Commemoration Day": "雄王纪念日",
    "Ninoy Aquino Day": "阿基诺日",
    "Bonifacio Day": "博尼法西奥日",
    "Rizal Day": "黎刹日",
    "Day of Valor": "勇气日",
    "Pancasila Day": "潘查希拉日",
    "National Day of the People's Republic of China": "国庆节",

    # 欧洲细节
    "German Unity Day": "德国统一日",
    "Day of German Unity": "德国统一日",
    "Russia Day": "俄罗斯日",
    "Defender of the Fatherland Day": "祖国保卫者日",
    "Day of Victory over Fascism": "战胜法西斯纪念日",
    "Day of Victory over the Genocidal Regime": "战胜种族灭绝政权纪念日",
    "Jan Hus Day": "扬·胡斯日",
    "Independent Czech State Restoration Day; New Year's Day": "捷克独立日 / 元旦",
    "Independent Czechoslovak State Day": "捷克斯洛伐克独立日",
    "Struggle for Freedom and Democracy Day and International Students' Day": "自由民主斗争日暨国际学生日",
    "Day of the Establishment of the Slovak Republic": "斯洛伐克共和国成立日",
    "Slovak National Uprising Anniversary": "斯洛伐克民族起义纪念日",
    "Unification of the Romanian Principalities Day": "罗马尼亚统一日",
    "Statehood Day (Croatia)": "国家日",
    "Day of Portugal, Camões, and the Portuguese Communities": "葡萄牙日",
    "National Day of the Third of May": "五月三日国庆日",
    "Constitution Day; Pentecost Monday": "宪法日 / 圣灵降临节星期一",
    "Ohi Day": "「不」日（希腊国庆）",
    "Independence Day (Greece)": "希腊独立日",
    "August Bank Holiday": "八月公假",
    "May Bank Holiday": "五月公假",
    "Spring Bank Holiday": "春季公假",
    "June Bank Holiday": "六月公假",
    "October Bank Holiday": "十月公假",
    "Summer Bank Holiday": "夏季公假",
    "Early May Bank Holiday": "五月初公假",
    "Saint Stephen's Day (Ireland)": "圣斯德望日",

    # 美洲细节
    "Benito Juárez's birthday": "华雷斯诞辰",
    "Universal Fraternization Day": "博爱日",
    "Tiradentes' Day": "蒂拉登特斯日",
    "National Day of Zumbi and Black Awareness": "尊比与黑人意识日",
    "National Day of Remembrance for Truth and Justice": "真相与正义纪念日",
    "May Revolution Day": "五月革命纪念日",
    "Battle of Boyacá": "博亚卡战役纪念日",
    "Battle of Ayacucho Day": "阿亚库乔战役纪念日",
    "Battle of Junín Day": "胡宁战役纪念日",
    "Battle of Angamos Day": "安加莫斯海战纪念日",
    "Battle of Arica and Flag Day": "阿里卡战役与国旗日",
    "Independence of Cartagena": "卡塔赫纳独立日",
    "Day of Our Lady of the Rosary of Chiquinquirá": "奇金基拉圣母念珠日",
    "Pass to the Immortality of General Don José de San Martín": "圣马丁将军逝世纪念日",
    "Pass to the Immortality of General Don Manuel Belgrano": "贝尔格拉诺将军逝世纪念日",
    "Pass to the Immortality of General Don Martín Miguel de Güemes": "圭梅斯将军逝世纪念日",
    "Veteran's Day and the Fallen in the Malvinas War": "马岛战争老兵纪念日",
    "National Sovereignty Day": "主权日",
    "National Sovereignty and Children's Day": "主权与儿童节",
    "Meeting of Two Worlds' Day": "两世界相遇日",
    "Respect for Cultural Diversity Day": "文化多样性日",
    "Commemoration of Atatürk, Youth and Sports Day": "阿塔图尔克纪念日暨青年体育节",
    "Democracy and National Unity Day": "民主与民族团结日",
    "National Day of the Third of May": "五月三日国庆日",

    # 非洲 / 中东细节
    "Sinai Liberation Day": "西奈解放日",
    "January 25th Revolution and National Police Day": "1·25 革命暨警察日",
    "June 30 Revolution Day": "6·30 革命日",
    "July 23 Revolution Day": "7·23 革命日",
    "July Mass Uprising Day": "七月起义纪念日",
    "Jamhuri Day": "独立日（肯尼亚）",
    "Madaraka Day": "自治日",
    "Mashujaa Day": "英雄日",
    "Mazingira Day": "环境日",
    "Oued Ed-Dahab Day": "达哈卜日",
    "Green March": "绿色进军纪念日",
    "National Democracy Day": "民主日",

    # 农历（港澳台）
    "Chinese New Year (Second Day)": "春节初二",
    "The second day of Chinese New Year": "农历年初二",
    "The third day of Chinese New Year": "农历年初三",
    "The fourth day of Chinese New Year": "农历年初四",
    "The day following Chinese New Year": "农历年初二",
    "Tomb-Sweeping Day": "清明节",
    "Ching Ming Festival": "清明节",
    "Dragon Boat Festival": "端午节",
    "Mid-Autumn Festival": "中秋节",
    "The Day following Mid-Autumn Festival": "中秋节翌日",
    "Double Ninth Festival": "重阳节",
    "Chung Yeung Festival": "重阳节",
    "Buddha's Birthday": "佛诞节",
    "Hong Kong S.A.R. Establishment Day": "香港特别行政区成立日",
    "Macao S.A.R. Establishment Day": "澳门特别行政区成立日",
    "National Day of the People's Republic of China": "国庆节",
    "Day after Christmas": "圣诞节后第一个周日",
    "The first weekday after Christmas Day": "圣诞节后第一个周日",

    "HM King Bhumibol Adulyadej the Great's Birthday": "普密蓬国王诞辰",
    "HM King Bhumibol Adulyadej the Great's Birthday; National Day; National Father's Day": "普密蓬国王诞辰暨国庆、父亲节",
    "National Father's Day": "父亲节",
    "National Mother's Day": "母亲节",
    "Independent Czech State Restoration Day": "捷克独立日",
    "Gai Tihar": "灯节",
    "Laxmi Pooja": "财神日",
    "Gobardhan Pooja": "牛节",
    "Mha Pooja": "自敬日",
    "Gyalpo Lhosar": "藏历新年",
    "Sonam Lhochhar": "塔芒新年",

    # 尾部落网（译名覆盖率检查剩下的 13 条）
    "National Festival and People's Revolution Anniversary": "国庆与人民革命纪念日",
    "Thadingyut Holidays": "点灯节",
    "Thadingyut Festival": "点灯节",
    "Substitute Holiday": "补假",
    "Black Saturday": "黑色星期六",
    "Union Day": "联邦日",
    "Full Moon Day of Tabaung": "德榜月圆日",
    "Full Moon Day of Kason": "葛宋月圆日",
    "Full Moon Day of Waso": "瓦梭月圆日",
    "Full Moon Day of Tazaungmon": "德桑蒙月圆日",
    "Epiphany (Three Kings' Day and Orthodox Christmas)": "主显节（三王节暨东正教圣诞）",
    "Carnival Monday": "狂欢节星期一",
    "Carnival Tuesday": "狂欢节星期二",
    "Peruvian Air Force Day": "秘鲁空军节",
}


_SUFFIX = [
    (" (observed, estimated)", "（补假·推算）"),
    (" (in lieu, estimated)", "（补假·推算）"),
    (" (observed)", "（补假）"),
    (" (in lieu)", "（补假）"),
    (" (estimated)", "（推算）"),
    (" (substitute)", "（补假）"),
]


# 同一个英文名在不同国家不是同一个节：埃及的 Spring Festival 是闻风节
# （Sham El Nessim，科普特复活节次日），不是中国的春节。这类必须按国家覆盖。
COUNTRY_OVERRIDE: dict[tuple[str, str], str] = {
    ("EG", "Spring Festival"): "闻风节（踏青节）",
    ("EG", "Coptic Christmas Day"): "科普特圣诞节",
    ("IL", "Passover"): "逾越节",
    ("IL", "Memorial Day"): "阵亡将士纪念日",
    ("JP", "Culture Day"): "文化日",
    ("KR", "Chuseok"): "秋夕（中秋）",
    ("TH", "National Day"): "国庆日（普密蓬诞辰）",
    ("JP", "Substitute Holiday"): "振替休日（补假）",
    ("JP", "National Holiday"): "国民之休日",
    ("QA", "National Day"): "国庆日",
}


def _split_suffix(name: str) -> tuple[str, str]:
    for en, zh in _SUFFIX:
        if name.endswith(en):
            return name[: -len(en)], zh
    return name, ""


def zh_name(name: str, code: str = "") -> str:
    """英文节日名 → 中文。未收录时按规则降级，最差保留英文。

    顺序很重要：先整词命中（"Gai Tihar; Laxmi Pooja" 是一整个键），
    再拆后缀（(observed)/(estimated)），最后才按 "; " 拆多节名——
    反过来会把整词词典永远打不中。
    """
    name = name.strip()

    if code and (code, name) in COUNTRY_OVERRIDE:
        return COUNTRY_OVERRIDE[(code, name)]

    if name in ZH:
        return ZH[name]

    base, suffix = _split_suffix(name)

    if code and (code, base) in COUNTRY_OVERRIDE:
        return COUNTRY_OVERRIDE[(code, base)] + suffix

    if base in ZH:
        return ZH[base] + suffix

    # 多节名（"A; B"）分别翻译
    if "; " in base:
        return " / ".join(zh_name(x, code) for x in base.split("; ")) + suffix

    # 「Alternative holiday for X」= X 的补假
    m = re.match(r"Alternative holiday for (.+)$", base)
    if m:
        return zh_name(m.group(1), code) + "（补假）"

    # 「Day off (substituted from 01/02/2027)」= 调休补假
    m = re.match(r"Day off \(substituted from (\d{2})/(\d{2})/(\d{4})\)$", base)
    if m:
        return f"补假（{int(m.group(1))} 月 {int(m.group(2))} 日调休）"

    # 「29 of Lunar New Year」= 农历腊月廿九
    m = re.match(r"(\d+) of Lunar New Year$", base)
    if m and m.group(1) == "29":
        return "农历腊月廿九" + suffix

    # 「(First|Second|Third|Fourth|Fifth) Day of Lunar New Year」
    m = re.match(r"(First|Second|Third|Fourth|Fifth) Day of Lunar New Year$", base)
    if m:
        n = {"First": "初一", "Second": "初二", "Third": "初三", "Fourth": "初四", "Fifth": "初五"}[m.group(1)]
        return "农历正月" + n + suffix

    # 兜底：常见词尾拼装，仍不通就留英文
    for tail, zh_tail in (
        (" Holiday", "假期"),
        (" Day", "日"),
        (" Anniversary", "纪念日"),
        (" Festival", "节"),
    ):
        if base.endswith(tail) and base[: -len(tail)] in ZH:
            return ZH[base[: -len(tail)]] + zh_tail + suffix

    return name


def country_zh(code: str) -> str:
    for c, _, zh, _, _ in COUNTRIES:
        if c == code:
            return zh
    return code
