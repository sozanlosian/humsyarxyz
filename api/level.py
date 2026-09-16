def get_level(pct: float) -> dict:
    if pct >= 90: return {"label":"خبره","icon":"🏆","key":"expert","color":"#FCD34D"}
    if pct >= 75: return {"label":"پیشرفته","icon":"⭐","key":"advanced","color":"#A78BFA"}
    if pct >= 60: return {"label":"متوسط","icon":"📈","key":"intermediate","color":"#60A5FA"}
    if pct >= 40: return {"label":"مبتدی","icon":"📚","key":"beginner","color":"#34D399"}
    return {"label":"تازه‌کار","icon":"🌱","key":"newbie","color":"#94A3B8"}
