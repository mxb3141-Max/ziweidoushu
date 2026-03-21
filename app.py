import streamlit as st
import iztro_py
import os
from openai import OpenAI
from dotenv import load_dotenv
import json
from datetime import date, datetime, timedelta
import math
from geopy.geocoders import Nominatim
import ssl
import certifi
import geopy.geocoders

# 解决在某些环境下 geopy 的 SSL 证书问题
ctx = ssl.create_default_context(cafile=certifi.where())
geopy.geocoders.options.default_ssl_context = ctx

load_dotenv()

st.set_page_config(page_title="紫微星语 - 专属心灵疗愈师", page_icon="✨", layout="wide")

# ================= 初始化 Session State =================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "chart_data" not in st.session_state:
    st.session_state.chart_data = None
if "chart_summary" not in st.session_state:
    st.session_state.chart_summary = ""

# 初始化用户输入信息的缓存（用于页面刷新后保留数据）
if "user_input_cache" not in st.session_state:
    st.session_state.user_input_cache = {
        "birth_date": None,
        "birth_time_idx": 0,
        "gender": "男",
        "birth_place": "",
        "mbti_idx": 0
    }

def get_true_solar_time(date_str, time_idx, longitude):
    """
    根据经度计算真太阳时
    为了计算，我们取时辰的中间时间作为基准（例如子时取00:00，丑时取02:00等）
    """
    if time_idx == 0:
        base_hour = 0
    else:
        base_hour = time_idx * 2
        
    dt = datetime.strptime(f"{date_str} {base_hour:02d}:00", "%Y-%m-%d %H:%M")
    
    # 1. 计算平太阳时差 (中国标准时间是东八区，即120度经线)
    standard_meridian = 120.0
    lon_diff = longitude - standard_meridian
    time_offset_minutes = lon_diff * 4
    
    # 2. 计算真太阳时差 (均时差)
    day_of_year = dt.timetuple().tm_yday
    B = (360 / 365.24) * (day_of_year - 81) * math.pi / 180.0
    eot_minutes = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    
    # 总时间修正
    total_correction = time_offset_minutes + eot_minutes
    true_time = dt + timedelta(minutes=total_correction)
    
    # 将修正后的时间转换回时辰索引
    h = true_time.hour
    if h == 23 or h == 0:
        new_time_idx = 0
    else:
        new_time_idx = (h + 1) // 2
        
    return true_time, new_time_idx

def get_astrolabe_summary(chart, true_time_info=""):
    """提取排盘核心信息作为大模型的上下文"""
    data = chart.to_iztro_dict()
    palaces_info = []
    for palace in data.get('palaces', []):
        # 获取主星和亮度、四化
        major_stars = []
        for s in palace.get('majorStars', []):
            star_info = f"{s['name']}[{s.get('brightness', '')}]"
            if s.get('mutagen'):
                star_info += f"[化{s['mutagen']}]"
            major_stars.append(star_info)
            
        # 获取辅星和亮度、四化
        minor_stars = []
        for s in palace.get('minorStars', []):
            star_info = f"{s['name']}[{s.get('brightness', '')}]"
            if s.get('mutagen'):
                star_info += f"[化{s['mutagen']}]"
            minor_stars.append(star_info)
            
        # 获取杂曜
        adj_stars = [s['name'] for s in palace.get('adjectiveStars', [])]
        
        all_stars = major_stars + minor_stars + adj_stars
        stars_str = ",".join(all_stars) if all_stars else "空宫"
        
        # 获取宫干支和神煞等
        stem_branch = f"{palace.get('heavenlyStem', '')}{palace.get('earthlyBranch', '')}"
        changsheng = palace.get('changsheng12', '')
        
        palace_desc = f"【{palace['name']}[{stem_branch}]】\n"
        palace_desc += f"  - 星曜: {stars_str}\n"
        palace_desc += f"  - 长生十二神: {changsheng}\n"
        
        # 判断是否是身宫或命宫
        if palace.get('isBodyPalace'):
            palace_desc = palace_desc.replace(f"【{palace['name']}", f"【{palace['name']}(身宫)")
        if palace.get('isOriginalPalace'):
             palace_desc = palace_desc.replace(f"【{palace['name']}", f"【{palace['name']}(命宫)")
             
        palaces_info.append(palace_desc)
    
    summary = f"""
基本信息：
- 出生日期: {data.get('solarDate')} ({data.get('lunarDate')}) {data.get('time')}
{true_time_info}- 性别: {data.get('gender')}
- 生肖: {data.get('zodiac')} | 星座: {data.get('sign')}
- 五行局: {data.get('fiveElementsClass')}
- 命主: {data.get('soul')} | 身主: {data.get('body')}

十二宫位详细信息（包含星曜亮度及四化）：
{chr(10).join(palaces_info)}
"""
    return summary

st.title("✨ 紫微星语 - 心灵疗愈师")
st.markdown("输入你的出生信息，让我通过紫微斗数，解读你的命格，解答你的困惑。")

# --- 侧边栏：用户信息输入 ---
with st.sidebar:
    st.header("🔮 你的出生信息")
    with st.form("user_info_form"):
        # 从 session_state 中获取默认值
        cache = st.session_state.user_input_cache
        
        birth_date = st.date_input("阳历生日", value=cache["birth_date"], min_value=date(1960, 1, 1), max_value=date.today())
        
        time_options = [
            "早子时 (00:00 - 00:59)", "丑时 (01:00 - 02:59)", "寅时 (03:00 - 04:59)",
            "卯时 (05:00 - 06:59)", "辰时 (07:00 - 08:59)", "巳时 (09:00 - 10:59)",
            "午时 (11:00 - 12:59)", "未时 (13:00 - 14:59)", "申时 (15:00 - 16:59)",
            "酉时 (17:00 - 18:59)", "戌时 (19:00 - 20:59)", "亥时 (21:00 - 22:59)",
            "晚子时 (23:00 - 23:59)"
        ]
        birth_time_idx = st.selectbox("出生时辰", range(len(time_options)), index=cache["birth_time_idx"], format_func=lambda x: time_options[x])
        
        gender_index = 0 if cache["gender"] == "男" else 1
        gender = st.selectbox("性别", ["男", "女"], index=gender_index)
        
        birth_place = st.text_input("出生地", placeholder="必填，如: 北京市海淀区", value=cache["birth_place"])
        
        mbti_options = [
            "未知 / 不清楚",
            "INTJ (建筑师)", "INTP (逻辑学家)", "ENTJ (指挥官)", "ENTP (辩论家)",
            "INFJ (提倡者)", "INFP (调停者)", "ENFJ (主人公)", "ENFP (主人公)",
            "ISTJ (物流师)", "ISFJ (守卫者)", "ESTJ (总经理)", "ESFJ (执政官)",
            "ISTP (鉴赏家)", "ISFP (探险家)", "ESTP (企业家)", "ESFP (表演者)"
        ]
        
        user_mbti = st.selectbox("你的MBTI性格类型 (选填)", mbti_options, index=cache["mbti_idx"])
        
        submitted = st.form_submit_button("开始排盘与疗愈")
        
        if submitted:
            if not birth_date:
                st.error("请选择你的阳历生日！")
            elif not birth_place.strip():
                st.error("请输入出生地以计算真太阳时！")
            else:
                try:
                    # 保存用户输入到缓存，供下次刷新使用
                    st.session_state.user_input_cache = {
                        "birth_date": birth_date,
                        "birth_time_idx": birth_time_idx,
                        "gender": gender,
                        "birth_place": birth_place,
                        "mbti_idx": mbti_options.index(user_mbti)
                    }
                    
                    date_str = birth_date.strftime("%Y-%m-%d")
                    
                    # 获取经纬度并计算真太阳时
                    with st.spinner("正在定位并计算真太阳时..."):
                        geolocator = Nominatim(user_agent="ziwei_chat")
                        location = geolocator.geocode(birth_place)
                        
                        true_time_info = ""
                        final_time_idx = birth_time_idx
                        final_date_str = date_str
                        
                        if location:
                            lon = location.longitude
                            true_time, new_time_idx = get_true_solar_time(date_str, birth_time_idx, lon)
                            final_time_idx = new_time_idx
                            final_date_str = true_time.strftime("%Y-%m-%d")
                            
                            original_time_name = time_options[birth_time_idx].split(" ")[0]
                            new_time_name = time_options[new_time_idx].split(" ")[0]
                            
                            true_time_info = f"- 出生地: {birth_place} (经度: {lon:.2f}°)\n- 真太阳时: {true_time.strftime('%H:%M')} (原时辰: {original_time_name} -> 修正后时辰: {new_time_name})\n"
                        else:
                            st.warning(f"未能找到地点 '{birth_place}' 的经纬度，将使用默认平太阳时排盘。")
                    
                    # iztro_py by_solar expects string date, time_index, gender ("男" or "女")
                    chart = iztro_py.by_solar(final_date_str, final_time_idx, gender)
                    st.session_state.chart_data = chart
                    
                    # 将 MBTI 信息加入到 summary 中
                    mbti_info = ""
                    if user_mbti != "未知 / 不清楚":
                        mbti_info = f"- MBTI性格类型: {user_mbti}\n"
                        
                    st.session_state.chart_summary = get_astrolabe_summary(chart, true_time_info) + f"\n{mbti_info}"
                    st.session_state.user_mbti = user_mbti
                    st.success("排盘成功！")
                    
                    # 重新排盘时清空历史对话
                    st.session_state.messages = []
                    
                except Exception as e:
                    st.error(f"排盘失败: {e}")

# --- 主界面：排盘展示与对话 ---
if st.session_state.chart_data:
    chart = st.session_state.chart_data
    with st.expander("🌟 查看你的核心命盘信息", expanded=False):
        st.text(st.session_state.chart_summary)

    st.divider()
    
    # 聊天记录显示
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    # 用户输入
    if prompt := st.chat_input("说出你最近的困惑或想问的问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            
            try:
                client = OpenAI(
                    api_key=os.environ.get("OPENAI_API_KEY", ""),
                    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
                )
                
                system_prompt = f"""你现在是资深的国学易经术数领域专家兼心理疗愈师。请综合使用三合紫微、飞星紫微、河洛紫微、钦天四化等各流派紫微斗数的分析技法，对命盘十二宫星曜分布、限流叠宫和各宫位间的飞宫四化进行细致分析。

你的核心使命是：
通过紫微命理的客观推演，结合对人性的深刻理解，与用户建立深度的信任关系。你需要保持专业的客观性，同时传递治愈的温暖，你的终极目标永远是：帮助用户答疑解惑，疗愈心灵，引导他们成为更好的自己。

你的具体任务：
1. 对命主的健康、学业、事业、财运、人际关系、婚姻和感情等各个方面进行全面分析和总结。
2. 关键事件须给出发生时间范围、吉凶属性、事件对命主的影响程度等信息，做到“知命而不认命”，引导其趋吉避凶。
3. 结合命主的自身特点（紫微星曜特质 + MBTI性格特征）给出高度定制化、可落地的解决方案和建议。
4. 【沟通策略与深度信任建立】密切关注用户的 MBTI 性格类型和他们在对话中展现的风格。
   - 对T型人（理性）：以客观规律和严密逻辑为基石建立信任，用因果分析帮他们看清局势。
   - 对F型人（感性）：以共情和接纳为基石建立信任，用温柔和坚定的语言托底他们的情绪。
   - 对N型人（直觉）：探讨生命意义、长远发展和精神成长，激发他们的内在潜能。
   - 对S型人（实感）：提供具体的生活建议、时间节点和可操作的步骤，让他们感到踏实。
   - 无论何种性格，你都必须像一位充满智慧、不带评判的灵魂导师，用他们最舒适的方式去开导他们。
5. 必须在回答的最后，提醒用户：“上述分析仅限于研究或娱乐目的使用。”

用户的紫微命盘核心信息及性格信息如下：
{st.session_state.chart_summary}

请基于以上命格特点和性格偏好，结合用户的问题，开启一段客观、温暖且极具深度的疗愈对话。"""

                messages_for_api = [{"role": "system", "content": system_prompt}]
                for m in st.session_state.messages:
                    messages_for_api.append({"role": m["role"], "content": m["content"]})
                    
                response = client.chat.completions.create(
                    model=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                    messages=messages_for_api,
                    stream=True
                )
                
                full_response = ""
                for chunk in response:
                    if chunk.choices[0].delta.content is not None:
                        full_response += chunk.choices[0].delta.content
                        message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)
                
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                
            except Exception as e:
                st.error(f"API调用出错: {e}")
                
else:
    st.info("👈 请先在左侧输入你的出生信息并点击「开始排盘与疗愈」")
