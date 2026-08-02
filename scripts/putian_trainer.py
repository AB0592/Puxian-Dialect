#!/usr/bin/env python3
"""
个人语言训练系统 — Streamlit Web 界面

四阶训练素材：字 → 词 → 句 → 文章
用户可选择方言语系或创建自己的语言系统。
系统学习用户的语音，逐步构建个人语音库。

启动: python3 -m streamlit run putian_trainer.py --server.port 8501
手机访问: 同一 WiFi 下 http://<本机IP>:8501
"""
import sys
import json
import os
from pathlib import Path
import tempfile
import time
import re

import streamlit as st
from st_audiorec import st_audiorec

# 确保脚本目录在路径上
SCRIPTS_DIR = Path(__file__).parent
PROFILE_DIR = SCRIPTS_DIR.parent
USER_DATA_DIR = PROFILE_DIR / "user_data"
AUDIO_CACHE = PROFILE_DIR / "audio_cache"
AUDIO_CACHE.mkdir(exist_ok=True)
USER_DATA_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPTS_DIR))
from dialect_map import load, save, add, lookup, stats, search as map_search
from dialect_asr import recognize as asr_recognize

# ============================================================
# 训练素材四级结构
# ============================================================

# --- 字 (Characters) — 基础汉字 ---
CHARS = [
    # 常用基本字
    ("一", "数字", 1), ("二", "数字", 1), ("三", "数字", 1), ("四", "数字", 1),
    ("五", "数字", 1), ("六", "数字", 1), ("七", "数字", 1), ("八", "数字", 1),
    ("九", "数字", 1), ("十", "数字", 1), ("百", "数字", 1), ("千", "数字", 1),
    ("万", "数字", 1), ("人", "人物", 1), ("大", "形容", 1), ("小", "形容", 1),
    ("上", "方位", 1), ("下", "方位", 1), ("中", "方位", 1), ("前", "方位", 1),
    ("后", "方位", 1), ("左", "方位", 1), ("右", "方位", 1), ("里", "方位", 1),
    ("外", "方位", 1), ("天", "自然", 1), ("地", "自然", 1), ("水", "自然", 1),
    ("火", "自然", 1), ("风", "自然", 1), ("山", "自然", 1), ("日", "自然", 1),
    ("月", "自然", 1), ("星", "自然", 1), ("云", "自然", 1), ("雨", "自然", 1),
    ("金", "物", 1), ("木", "物", 1), ("土", "物", 1), ("石", "物", 1),
    ("门", "物", 1), ("口", "身体", 1), ("手", "身体", 1), ("目", "身体", 1),
    ("心", "身体", 1), ("头", "身体", 1), ("足", "身体", 1), ("耳", "身体", 1),
    ("牙", "身体", 1), ("鼻", "身体", 1),
    # Level 2
    ("你", "代词", 2), ("我", "代词", 2), ("他", "代词", 2), ("她", "代词", 2),
    ("好", "形容", 2), ("多", "形容", 2), ("少", "形容", 2), ("长", "形容", 2),
    ("短", "形容", 2), ("高", "形容", 2), ("矮", "形容", 2), ("胖", "形容", 2),
    ("瘦", "形容", 2), ("冷", "形容", 2), ("热", "形容", 2), ("快", "形容", 2),
    ("慢", "形容", 2), ("新", "形容", 2), ("旧", "形容", 2), ("远", "形容", 2),
    ("近", "形容", 2), ("来", "动词", 2), ("去", "动词", 2), ("走", "动词", 2),
    ("跑", "动词", 2), ("吃", "动词", 2), ("喝", "动词", 2), ("说", "动词", 2),
    ("看", "动词", 2), ("听", "动词", 2), ("做", "动词", 2), ("买", "动词", 2),
    ("卖", "动词", 2), ("有", "动词", 2), ("是", "动词", 2), ("要", "动词", 2),
    ("会", "动词", 2), ("能", "动词", 2), ("想", "动词", 2), ("爱", "动词", 2),
    ("笑", "动词", 2), ("哭", "动词", 2), ("坐", "动词", 2), ("站", "动词", 2),
    ("睡", "动词", 2), ("飞", "动词", 2), ("开", "动词", 2), ("关", "动词", 2),
]

# --- 词 (Words) — 常用词汇 ---
WORDS = [
    # Level 1: 基础
    ("我们", "代词", 1), ("你们", "代词", 1), ("他们", "代词", 1),
    ("今天", "时间", 1), ("明天", "时间", 1), ("昨天", "时间", 1),
    ("早上", "时间", 1), ("中午", "时间", 1), ("晚上", "时间", 1),
    ("现在", "时间", 1), ("几点", "时间", 1), ("什么时候", "时间", 1),
    ("不好", "形容", 1), ("开心", "情感", 1), ("难过", "情感", 1),
    ("生气", "情感", 1), ("害怕", "情感", 1), ("喜欢", "情感", 1),
    ("不是", "动词", 1), ("没有", "动词", 1), ("知道", "动词", 1),
    ("想要", "动词", 1), ("可以", "动词", 1),
    ("多少钱", "疑问", 1), ("哪里", "疑问", 1), ("什么", "疑问", 1),
    ("为什么", "疑问", 1), ("怎么", "疑问", 1), ("谁", "疑问", 1),
    ("是不是", "疑问", 1), ("有没有", "疑问", 1),
    # Level 2: 日常
    ("吃饭", "日常", 2), ("喝水", "日常", 2), ("睡觉", "日常", 2),
    ("起床", "日常", 2), ("上班", "日常", 2), ("下班", "日常", 2),
    ("回家", "日常", 2), ("出门", "日常", 2), ("洗澡", "日常", 2),
    ("穿衣服", "日常", 2), ("做饭", "日常", 2), ("洗碗", "日常", 2),
    ("扫地", "日常", 2), ("洗衣服", "日常", 2), ("喝茶", "日常", 2),
    ("谢谢", "日常", 2), ("对不起", "日常", 2), ("没关系", "日常", 2),
    ("你好", "日常", 2), ("再见", "日常", 2), ("欢迎", "日常", 2),
    ("恭喜", "日常", 2), ("辛苦了", "日常", 2), ("麻烦你了", "日常", 2),
    ("不要", "动词", 2), ("不会", "动词", 2), ("不能", "动词", 2),
    ("好喝", "形容", 2), ("好吃", "形容", 2), ("好看", "形容", 2),
    ("好听", "形容", 2), ("漂亮", "形容", 2), ("难看", "形容", 2),
    ("聪明", "形容", 2), ("笨", "形容", 2), ("干净", "形容", 2),
    ("脏", "形容", 2), ("贵", "形容", 2), ("便宜", "形容", 2),
    ("脱衣服", "日常", 2),
    # Level 3: 场景
    ("家", "地点", 3), ("学校", "地点", 3), ("医院", "地点", 3),
    ("超市", "地点", 3), ("市场", "地点", 3), ("饭馆", "地点", 3),
    ("公司", "地点", 3), ("公园", "地点", 3), ("车站", "地点", 3),
    ("厕所", "地点", 3), ("楼上", "地点", 3), ("楼下", "地点", 3),
    ("里面", "地点", 3), ("外面", "地点", 3), ("前面", "地点", 3),
    ("后面", "地点", 3), ("左边", "地点", 3), ("右边", "地点", 3),
    ("饭", "饮食", 3), ("菜", "饮食", 3), ("肉", "饮食", 3), ("鱼", "饮食", 3),
    ("鸡", "饮食", 3), ("鸭", "饮食", 3), ("蛋", "饮食", 3), ("面", "饮食", 3),
    ("粥", "饮食", 3), ("汤", "饮食", 3), ("水果", "饮食", 3), ("茶", "饮食", 3),
    ("咖啡", "饮食", 3), ("牛奶", "饮食", 3), ("酒", "饮食", 3),
    ("书", "物品", 3), ("笔", "物品", 3), ("纸", "物品", 3),
    ("手机", "物品", 3), ("电脑", "物品", 3), ("电视", "物品", 3),
    ("桌子", "物品", 3), ("椅子", "物品", 3), ("床", "物品", 3),
    ("门", "物品", 3), ("窗", "物品", 3), ("灯", "物品", 3),
    ("衣服", "物品", 3), ("裤子", "物品", 3), ("鞋子", "物品", 3),
    ("钱", "物品", 3), ("钥匙", "物品", 3), ("伞", "物品", 3),
    ("钱包", "物品", 3), ("背包", "物品", 3), ("眼镜", "物品", 3),
    ("抽烟", "日常", 2),
]

# --- hinghwa.cn 莆仙话发音词 (自动注入 126 条) ---
try:
    _hw_ref = json.loads((PROFILE_DIR / "data" / "hinghwa" / "reference.json").read_text(encoding="utf-8"))
    _hw_words = [(k, "莆仙话", 3) for k, v in _hw_ref.items() if v.get("audio_variants")]
    WORDS.extend(_hw_words)
except Exception:
    pass

# --- 句 (Sentences) — 常用句子 ---
SENTENCES = [
    ("你好吗", "问候", 1), ("我很好", "问候", 1),
    ("你叫什么名字", "介绍", 1), ("很高兴认识你", "介绍", 1),
    ("你从哪里来", "介绍", 1), ("你住在哪里", "介绍", 1),
    ("你做什么工作", "介绍", 1), ("你吃饭了吗", "日常", 1),
    ("我吃饭了", "日常", 1), ("你要去哪里", "日常", 1),
    ("这个多少钱", "购物", 1), ("太贵了", "购物", 1),
    ("便宜一点", "购物", 1),
    ("我喜欢你", "情感", 2), ("我想你", "情感", 2),
    ("好久不见", "问候", 2), ("明天见", "问候", 2),
    ("今天天气真好", "日常", 2), ("下雨了", "日常", 2),
    ("天冷了", "日常", 2), ("天热了", "日常", 2),
    ("请坐", "礼貌", 2), ("请喝茶", "礼貌", 2),
    ("慢走", "礼貌", 2), ("一路平安", "祝福", 2),
    ("生日快乐", "祝福", 2), ("新年快乐", "祝福", 2),
    ("恭喜发财", "祝福", 2), ("身体健康", "祝福", 2),
    ("我不知道", "表达", 2), ("我不明白", "表达", 2),
    ("请再说一遍", "表达", 2), ("说慢一点", "表达", 2),
    ("可以帮我吗", "请求", 2), ("没问题", "回应", 2),
    ("我叫...", "介绍", 1), ("我从...来", "介绍", 1),
    ("我住在...", "介绍", 1), ("我要去...", "日常", 1),
    ("我是...", "介绍", 1),
]

# --- 文章 (Articles) — 短文 ---
ARTICLES = [
    {
        "title": "自我介绍",
        "level": 1,
        "content": "你好！我叫小明。我今年二十岁。我是中国人，我从北京来。我喜欢吃北京烤鸭。我的爱好是看书和听音乐。很高兴认识你！"
    },
    {
        "title": "我的一天",
        "level": 1,
        "content": "我每天早上七点起床。刷牙洗脸后，我吃早餐。早上八点我去上班。中午十二点我吃午饭。下午六点我下班回家。晚上我吃饭、看电视，然后十点睡觉。"
    },
    {
        "title": "去超市",
        "level": 2,
        "content": "今天下午，我和妈妈去超市买东西。我们买了很多好吃的东西：有苹果、香蕉，还有牛奶和面包。妈妈还买了鱼和鸡蛋。超市里的人很多，收银台前排了很长的队。我们付了钱，就回家了。"
    },
    {
        "title": "天气",
        "level": 2,
        "content": "北京的春天很暖和，但是有时候会刮大风。夏天很热，经常下雨。秋天是最舒服的季节，天气凉爽，树叶变黄了，非常漂亮。冬天很冷，会下雪。我最喜欢秋天。"
    },
    {
        "title": "我的家乡",
        "level": 3,
        "content": "我的家乡在福建莆田，是一个美丽的海滨城市。这里有很多好吃的特产，比如荔枝、龙眼和兴化米粉。莆田也有很长的历史，有著名的湄洲岛和广化寺。家乡的人们很热情好客。虽然我现在住在别的城市，但我非常想念家乡。"
    },
]

# ============================================================
# hinghwa.cn 莆仙话参考数据
# ============================================================
HINGHWA_DATA = None
HINGHWA_AUDIO_DIR = PROFILE_DIR / "data" / "hinghwa" / "audio"

def load_hinghwa_reference():
    """加载 hinghwa.cn 莆仙话词典作为参考发音"""
    global HINGHWA_DATA
    if HINGHWA_DATA is not None:
        return HINGHWA_DATA
    ref_path = PROFILE_DIR / "data" / "hinghwa" / "reference.json"
    if ref_path.exists():
        HINGHWA_DATA = json.loads(ref_path.read_text(encoding="utf-8"))
    else:
        HINGHWA_DATA = {}
    return HINGHWA_DATA

def get_hinghwa_pron(text: str) -> list:
    """查询莆仙话参考发音 — 精确词条匹配，返回 [{word, pinyin, ipa, audio_variants: [{county, town, pinyin, ipa, audio_file}]}]"""
    ref = load_hinghwa_reference()
    entry = ref.get(text)
    if entry and entry.get('audio_variants'):
        return [entry]
    return []

def get_hinghwa_audio_path(entry: dict) -> str:
    """获取第一个参考音频本地路径"""
    variants = entry.get('audio_variants', [])
    if variants:
        fname = variants[0].get('audio_file', '')
        if fname:
            return str(HINGHWA_AUDIO_DIR / fname)
    return ""


# 分类名称映射
CAT_NAMES = {
    "数字": "数字", "人物": "人物", "形容": "形容词", "方位": "方位",
    "自然": "自然", "物": "物品", "身体": "身体", "代词": "代词",
    "动词": "动词", "时间": "时间", "情感": "情感", "疑问": "疑问词",
    "日常": "日常用语", "地点": "地点", "饮食": "饮食", "物品": "物品",
    "问候": "问候", "介绍": "介绍", "购物": "购物", "礼貌": "礼貌",
    "祝福": "祝福", "表达": "表达", "请求": "请求", "回应": "回应",
}

DIALECT_FAMILIES = {
    "puxian": {"label": "莆仙话", "desc": "基于 HinghuaFactory 29k 词库"},
    "canton": {"label": "粤语", "desc": "广府话 / 广东话"},
    "minnan": {"label": "闽南语", "desc": "福建闽南话 / 台语"},
    "custom": {"label": "自定义", "desc": "创建自己的语言系统，从零开始"},
}

ASR_LANG_MAP = {
    "puxian": "putian", "canton": "canton",
    "minnan": "minnan", "custom": "auto",
}


# ============================================================
# 用户系统
# ============================================================

def get_user_dir(username: str) -> Path:
    d = USER_DATA_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_overlay(username: str) -> dict:
    path = get_user_dir(username) / "overlay.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_overlay(username: str, data: dict):
    path = get_user_dir(username) / "overlay.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user_profile(username: str) -> dict:
    path = get_user_dir(username) / "profile.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"name": username, "dialect": "puxian", "created": int(time.time())}


def save_user_profile(username: str, profile: dict):
    path = get_user_dir(username) / "profile.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def get_existing_users() -> list:
    users = []
    for d in USER_DATA_DIR.iterdir():
        if d.is_dir() and (d / "profile.json").exists():
            p = json.loads((d / "profile.json").read_text(encoding="utf-8"))
            users.append({"name": d.name, "dialect": p.get("dialect", "puxian")})
    return sorted(users, key=lambda x: x["name"])


def get_overlay_progress(username: str) -> int:
    return len(load_overlay(username))


def get_training_progress(username: str, material_type: str, materials: list) -> tuple:
    """返回 (已训练数, 总数) — 只统计用户个人录入，不含基础词库"""
    overlay = load_overlay(username)
    personal_keys = set(overlay.keys())
    personal_vals = set(overlay.values())

    if material_type == "char":
        items = CHARS
    elif material_type == "word":
        items = WORDS
    elif material_type == "sentence":
        items = SENTENCES
    elif material_type == "article":
        items = ARTICLES
    else:
        items = materials

    if material_type == "article":
        covered = sum(1 for a in items if a["title"] in personal_keys or a["title"] in personal_vals)
    else:
        covered = sum(1 for item in items
                      if item[0] in personal_keys or item[0] in personal_vals)
    return covered, len(items)


# ============================================================
# 训练工具函数
# ============================================================

def save_audio(audio_bytes: bytes) -> str:
    path = AUDIO_CACHE / f"rec_{int(time.time()*1000)}.wav"
    with open(path, "wb") as f:
        f.write(audio_bytes)
    return str(path)


def get_material_text(material_type: str, item) -> str:
    if material_type == "article":
        return item["content"]
    return item[0]


def get_material_label(material_type: str, item) -> str:
    if material_type == "article":
        return item["title"]
    return item[0]


def get_material_cat(material_type: str, item) -> str:
    if material_type == "article":
        return f"文章 Lv{item['level']}"
    return f"{CAT_NAMES.get(item[1], item[1])}  Lv{item[2]}"


def get_materials(material_type: str):
    if material_type == "char":
        return CHARS
    elif material_type == "word":
        return WORDS
    elif material_type == "sentence":
        return SENTENCES
    elif material_type == "article":
        return ARTICLES
    return []


def add_to_overlay(username: str, dialect_text: str, chinese: str):
    overlay = load_overlay(username)
    overlay[dialect_text.strip()] = chinese.strip()
    save_overlay(username, overlay)
    # Also add to global map for cross-user sharing
    try:
        add(dialect_text.strip(), chinese.strip())
    except:
        pass


def lookup_meaning(text: str, username: str) -> str:
    """查映射：先查个人覆盖层，再查基础词库"""
    overlay = load_overlay(username)
    if text in overlay:
        return overlay[text]
    base = lookup(text)
    if base:
        return base
    return text  # 没有匹配就返回原文


def text_to_speech(text: str, dialect: str) -> str:
    """TTS 合成语音（用 CosyVoice API 或 Edge TTS 回退）"""
    try:
        from dialect_tts import synthesize
        result = synthesize(text, lang=dialect)
        if result and os.path.exists(result):
            return result
    except:
        pass
    return ""


# ============================================================
# Streamlit UI
# ============================================================

st.set_page_config(
    page_title="个人语言训练系统",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 标题 ---
st.title("个人语言训练系统")
st.markdown("**看中文 → 用自己的语音朗读 → 系统记住你的发音**  "
            "四级素材：字 → 词 → 句 → 文章")

# ============================================================
# 侧边栏：用户 + 方言语系 + 进度
# ============================================================
with st.sidebar:
    st.header("用户")

    existing = get_existing_users()
    user_names = [u["name"] for u in existing]

    col_n, col_a = st.columns([3, 1])
    with col_n:
        if existing:
            selected_user = st.selectbox(
                "选择已有用户", [""] + user_names,
                key="user_select",
            )
        else:
            selected_user = ""

    with col_a:
        if st.button("新建", use_container_width=True):
            st.session_state.show_new_user = True

    if st.session_state.get("show_new_user") or (not existing and not selected_user):
        with st.form("new_user_form"):
            new_name = st.text_input("用户名", key="new_user_name").strip()
            new_dialect = st.selectbox(
                "方言语系",
                options=list(DIALECT_FAMILIES.keys()),
                format_func=lambda k: f"{DIALECT_FAMILIES[k]['label']} — {DIALECT_FAMILIES[k]['desc']}",
            )
            submitted = st.form_submit_button("创建并进入", type="primary")
            if submitted and new_name:
                profile = {"name": new_name, "dialect": new_dialect,
                           "created": int(time.time())}
                save_user_profile(new_name, profile)
                st.session_state.current_user = new_name
                st.session_state.show_new_user = False
                st.rerun()

    # 当前用户
    current_user = None
    current_dialect = "puxian"
    if selected_user:
        current_user = selected_user
    elif st.session_state.get("current_user"):
        current_user = st.session_state.current_user

    if current_user:
        profile = get_user_profile(current_user)
        current_dialect = profile.get("dialect", "puxian")
        family = DIALECT_FAMILIES.get(current_dialect, DIALECT_FAMILIES["custom"])

        st.success(f"{current_user}  ·  {family['label']}")

        # ASR 限制提示
        if current_dialect == "puxian":
            st.warning("ASR 不支持莆仙话 — 语音识别将按普通话处理。听读训练请使用侧边栏发音库。")

        if st.button("切换用户 / 退出"):
            for k in ["current_user", "user_select", "show_new_user"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.divider()

    if current_user:
        st.header("训练进度")

        mt_labels = {"char": "字", "word": "词", "sentence": "句", "article": "文章"}
        for mt in ["char", "word", "sentence", "article"]:
            mats = get_materials(mt)
            if mats:
                done, total = get_training_progress(current_user, mt, mats)
                col_l, col_r = st.columns([2, 1])
                with col_l:
                    st.caption(f"{mt_labels[mt]}  ({done}/{total})")
                with col_r:
                    pct = int(done / max(total, 1) * 100)
                    st.caption(f"{pct}%")
                st.progress(done / max(total, 1), text="")

        overlay_count = get_overlay_progress(current_user)
        st.metric("个人已录入", overlay_count)

        # 基础词库统计
        base_map = load()
        st.caption(f"基础词库: {len(base_map)} 条 ({family['label']})")

    st.divider()

    # --- 莆仙话发音库 (hinghwa.cn) ---
    if current_user and current_dialect == "puxian":
        with st.expander("**莆仙话发音库** (hinghwa.cn)", expanded=False):
            ref = load_hinghwa_reference()
            if ref:
                words_with_audio = [(k, v) for k, v in ref.items() if v.get('audio_variants')]
                st.caption(f"共 **{len(words_with_audio)}** 条带发音的词条 (hinghwa.cn 词典)")
                for word, entry in words_with_audio[:15]:
                    variants = entry.get('audio_variants', [])
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.markdown(f"**{word}**")
                        if variants:
                            v0 = variants[0]
                            st.caption(f"{v0.get('pinyin','')}  [{v0.get('county','')}/{v0.get('town','')}]")
                    with cols[1]:
                        audio_path = get_hinghwa_audio_path(entry)
                        if audio_path and os.path.exists(audio_path):
                            with open(audio_path, 'rb') as af:
                                st.audio(af.read(), format='audio/mp3')

# ============================================================
# 主界面 — 仅在用户登录后显示
# ============================================================

if not current_user:
    st.info("请先在左侧侧边栏选择或创建用户")
    st.stop()

# --- 共享录音机 ---
st.divider()
st.markdown("**录音机 — 点击 Start Recording 开始，点击 Stop 结束**")
audio_bytes = st_audiorec()
if audio_bytes:
    st.audio(audio_bytes, format="audio/wav")
    st.session_state["shared_audio"] = audio_bytes
else:
    if "shared_audio" in st.session_state:
        del st.session_state["shared_audio"]

# --- 训练素材 Tab ---
mt_labels = {"char": "字 · 基础汉字", "word": "词 · 常用词汇",
             "sentence": "句 · 常用句子", "article": "文章 · 短文"}
tabs = st.tabs([mt_labels[k] for k in ["char", "word", "sentence", "article"]])

for tab_idx, material_type in enumerate(["char", "word", "sentence", "article"]):
    with tabs[tab_idx]:
        materials = get_materials(material_type)
        if not materials:
            st.info(f"{mt_labels[material_type]} 暂无素材")
            continue

        # 进度 + 筛选
        done, total = get_training_progress(current_user, material_type, materials)

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            option = st.radio(
                "训练模式",
                ["未录入优先", "全部", "复习已录入"],
                horizontal=True,
                key=f"mode_{material_type}",
            )
        with col2:
            st.caption(f"进度: {done}/{total}")
            st.progress(done / max(total, 1))

        # 构建训练列表
        mapping = load()
        overlay = load_overlay(current_user)
        all_map = dict(mapping)
        all_map.update(overlay)
        known = set(all_map.values()) | set(all_map.keys())

        training_items = []
        for item in materials:
            label = get_material_label(material_type, item)
            in_known = label in known
            if option == "未录入优先" and in_known:
                continue
            if option == "复习已录入" and not in_known:
                continue
            training_items.append(item)

        if not training_items:
            st.success("当前模式下的素材已全部录入！切换模式继续。")
            continue

        # 当前训练项
        idx_key = f"idx_{material_type}_{current_user}"
        if idx_key not in st.session_state:
            st.session_state[idx_key] = 0

        idx = st.session_state[idx_key] % len(training_items)
        item = training_items[idx]
        label = get_material_label(material_type, item)
        cat = get_material_cat(material_type, item)

        st.subheader(f"{idx + 1} / {len(training_items)}")
        st.caption(cat)

        # 大字/段落显示内容
        if material_type == "article":
            st.markdown(
                f"<div style='font-size:1.5em; padding:30px; background:#f0f2f6; "
                f"border-radius:15px; margin:15px 0; line-height:1.8'>"
                f"<b>{item['title']}</b><br><br>{item['content']}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='text-align:center; font-size:4em; "
                f"padding:40px; background:#f0f2f6; border-radius:20px; "
                f"margin:20px 0'>{label}</div>",
                unsafe_allow_html=True,
            )

        st.markdown(f"**用你的语言朗读上面的内容**")

        # --- hinghwa.cn 参考发音 ---
        hinghwa_results = get_hinghwa_pron(label)
        if hinghwa_results:
            with st.expander("**莆仙话参考** (hinghwa.cn)", expanded=len(hinghwa_results) <= 2):
                for hr in hinghwa_results[:3]:
                    variants = hr.get('audio_variants', [])
                    cols = st.columns([2, 3])
                    with cols[0]:
                        st.markdown(f"**{hr.get('word', label)}**")
                        for v in variants[:2]:
                            st.caption(f"{v.get('pinyin','')} [{v.get('county','')}/{v.get('town','')}]")
                        if hr.get('definition'):
                            st.caption(f"释义: {hr['definition'][:80]}")
                    with cols[1]:
                        audio_path = get_hinghwa_audio_path(hr)
                        if audio_path and os.path.exists(audio_path):
                            with open(audio_path, 'rb') as af:
                                st.audio(af.read(), format='audio/mp3')
                        else:
                            st.caption(f"**{len(variants)}** 个发音变体")

        # 处理录音
        shared_audio = st.session_state.get("shared_audio")
        if shared_audio:
            col_a, col_b, col_c, col_d = st.columns([2, 1, 1, 1])

            with col_a:
                if st.button("确认并提交", type="primary", use_container_width=True, key=f"submit_{material_type}_{idx}"):
                    audio_path = save_audio(shared_audio)
                    lang = ASR_LANG_MAP.get(current_dialect, "auto")

                    with st.spinner("正在识别..."):
                        asr_result = asr_recognize(audio_path, lang)
                    dialect_text = asr_result.get("text", "").strip()

                    if dialect_text:
                        add_to_overlay(current_user, dialect_text, label)
                        st.success(f"已记录: {dialect_text}  ->  {label}")
                        st.session_state.pop("shared_audio", None)
                        st.session_state[idx_key] = idx + 1
                        st.rerun()
                    else:
                        st.warning("未能识别出语音")

                        with st.form(key=f"manual_form_{material_type}_{idx}"):
                            manual = st.text_input("手动输入你的发音：")
                            if st.form_submit_button("手动提交"):
                                if manual.strip():
                                    add_to_overlay(current_user, manual.strip(), label)
                                    st.success(f"已记录: {manual}  ->  {label}")
                                    st.session_state.pop("shared_audio", None)
                                    st.session_state[idx_key] = idx + 1
                                    st.rerun()

            with col_b:
                if st.button("跳过", use_container_width=True, key=f"skip_{material_type}_{idx}"):
                    st.session_state.pop("shared_audio", None)
                    st.session_state[idx_key] = idx + 1
                    st.rerun()

            with col_c:
                if st.button("重录", use_container_width=True, key=f"retry_{material_type}_{idx}"):
                    st.session_state.pop("shared_audio", None)
                    st.rerun()

            with col_d:
                # 添加到错词本
                if st.button("太难了", use_container_width=True, key=f"hard_{material_type}_{idx}"):
                    hard = st.session_state.get("hard_words", [])
                    hard.append(label)
                    st.session_state.hard_words = hard
                    st.session_state[idx_key] = idx + 1
                    st.rerun()
        else:
            st.info("请在上方录音机录音后点击确认")

        # 手动输入备选
        with st.expander("手动输入"):
            manual_text = st.text_input("输入你的发音（用汉字或拼音）", key=f"manual_{material_type}_{idx}")
            if st.button(f"手动提交 ({label})") and manual_text.strip():
                add_to_overlay(current_user, manual_text.strip(), label)
                st.success(f"已记录: {manual_text}  ->  {label}")
                st.session_state[idx_key] = idx + 1
                st.rerun()

# ============================================================
# 自由对话 + 模拟回复 Tab
# ============================================================

st.divider()
st.header("自由对话 / 模拟回复")

col_talk, col_reply = st.columns([1, 1])

with col_talk:
    st.subheader("说一句")
    shared_audio = st.session_state.get("shared_audio")
    if shared_audio:
        if st.button("识别并翻译", type="primary"):
            audio_path = save_audio(shared_audio)
            lang = ASR_LANG_MAP.get(current_dialect, "auto")
            with st.spinner("ASR 识别中..."):
                asr_result = asr_recognize(audio_path, lang)
            dialect_text = asr_result.get("text", "").strip()

            if dialect_text:
                st.session_state["talk_result"] = dialect_text
                chinese = lookup_meaning(dialect_text, current_user)
                st.session_state["talk_chinese"] = chinese
            else:
                st.error("未能识别")
    else:
        st.info("请先在上方录音机录音")

    if "talk_result" in st.session_state:
        dt = st.session_state["talk_result"]
        cn = st.session_state["talk_chinese"]
        st.markdown("**识别结果**")
        st.code(dt)
        st.markdown("**中文含义**")
        st.markdown(f"<div style='font-size:2em; padding:15px; background:#e8f5e9; border-radius:10px'>{cn}</div>",
                    unsafe_allow_html=True)

        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            if st.button("正确"):
                if dt != cn:
                    add_to_overlay(current_user, dt, cn)
                st.success("已确认")
                for k in ["talk_result", "talk_chinese"]:
                    st.session_state.pop(k, None)
                st.rerun()
        with col_c2:
            st.session_state["correcting_talk"] = True
        with col_c3:
            st.info("跳过")

        if st.session_state.get("correcting_talk"):
            correct = st.text_input("输入正确的中文含义：")
            if st.button("提交修正") and correct.strip():
                add_to_overlay(current_user, dt, correct.strip())
                st.success(f"已修正: {dt}  ->  {correct}")
                st.session_state["correcting_talk"] = False
                for k in ["talk_result", "talk_chinese"]:
                    st.session_state.pop(k, None)
                st.rerun()

with col_reply:
    st.subheader("模拟回复")

    reply_text = st.text_input("输入你想让系统回答的中文：",
                               placeholder="比如：你好，今天天气真好")

    if st.button("用你的语音风格回答"):
        st.info("TTS 合成功能开发中 — 将用个人语音库生成回复语音")

    # 展示个人语音库统计
    st.divider()
    st.caption("你的个人语音库")
    overlay = load_overlay(current_user)
    if overlay:
        items = list(overlay.items())
        for d, c in items[-10:]:
            st.write(f"{d}  ->  {c}")
        if len(items) > 10:
            st.caption(f"... 还有 {len(items) - 10} 条")
    else:
        st.caption("还没有录入数据，开始训练吧")

# ============================================================
# 知识库浏览 Tab
# ============================================================

with st.expander("知识库（查看所有已录入的映射）"):
    mt = st.radio("查看", ["个人词库", "基础词库", "全部"], horizontal=True)
    if mt == "个人词库":
        data = load_overlay(current_user)
        src = "个人"
    elif mt == "基础词库":
        data = load()
        src = "基础"
    else:
        data = dict(load())
        data.update(load_overlay(current_user))
        src = "全部"

    search_term = st.text_input("搜索", key="kb_search_main")
    if search_term:
        results = [(k, v) for k, v in data.items() if search_term in k or search_term in v]
    else:
        results = list(data.items())
        results.sort()

    if results:
        st.caption(f"{src}: 共 {len(results)} 条")
        per_page = 30
        pages = max(1, (len(results) + per_page - 1) // per_page)
        page = st.number_input("页码", 1, pages, 1)
        start = (page - 1) * per_page
        for k, v in results[start:start + per_page]:
            st.write(f"**{k}**  ->  {v}")
