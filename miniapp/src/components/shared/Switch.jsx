// ── HumsYar Switch — تک‌منبعِ حقیقتِ همه‌ی Toggleهای مینی‌اپ
//
// چرا بازطراحی شد (باگِ واقعیِ گزارش‌شده): در کارت‌های تیره‌ی مینی‌اپ،
// سوییچ روشن حس می‌داد از یک UI دیگر آمده. ریشه‌اش رنگ نبود، «وزنِ
// بصری» بود:
//   ۱) حالت ON از `--grad-brand` استفاده می‌کرد — یک گرادیانِ سه‌ایستگاهیِ
//      آبی→فیروزه‌ای که برای CTAهای بزرگ ساخته شده، نه برای یک کنترلِ
//      ۴۶px. همان گرادیان روی این ابعاد اشباع و «نئون» خوانده می‌شد.
//   ۲) نوب ۲۰px داخل تراکِ ۲۷px ⇒ فقط ۳٫۵px هوا؛ نوب مثل یک دیسکِ سفیدِ
//      چسبیده به لبه دیده می‌شد، نه یک عنصرِ شناور.
//   ۳) `--ease-spring` (cubic-bezier با overshoot=1.56) روی هر تاگل یک
//      پرشِ کوچک می‌داد ⇒ حسِ «iOS clone»، خلافِ زبانِ آرامِ بقیه‌ی UI.
//
// این کامپوننت هر سه را اصلاح می‌کند و تنها جایی است که ظاهر سوییچ
// تعریف می‌شود. تغییر رنگ/شعاع/اندازه در آینده = فقط همین فایل + توکن‌ها.
//
// معماری (طبق قرارداد پروژه): این کامپوننت **controlled** است و خودش
// هیچ‌وقت API صدا نمی‌زند؛ صاحبِ داده همیشه parent است. همین باعث
// می‌شود در پروفایل/تنظیمات/اعلان‌ها/ادمین بدون تغییر منطق مصرف شود.

import { haptic } from '../../lib/telegram';

export default function Switch({
  on,
  onToggle,
  disabled = false,
  loading = false,
  danger = false,
  color,
  label,
  describedBy,
  id,
}) {
  // در حالت loading کنترل غیرفعال است ولی *ظاهرِ* disabled را نمی‌گیرد،
  // چون کاربر باید بفهمد «در حال ذخیره» است نه «غیرفعال».
  const locked = disabled || loading;

  const handleClick = () => {
    if (locked) return;
    // Haptic صرفاً بهبودِ تدریجی است: خودِ helper با safeCall پوشانده
    // شده، پس روی کلاینتِ بدون پشتیبانی هیچ استثنایی رخ نمی‌دهد.
    haptic('light');
    onToggle?.(!on);
  };

  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={on}
      aria-busy={loading || undefined}
      aria-describedby={describedBy}
      aria-label={label || (on ? 'روشن' : 'خاموش')}
      disabled={locked}
      data-loading={loading ? '' : undefined}
      className={
        'hy-switch'
        + (on ? ' hy-switch--on' : '')
        + (danger ? ' hy-switch--danger' : '')
        + (color && on ? ' hy-switch--custom' : '')
      }
      // تنها استثنای inline-style: رنگِ دلخواهِ فراخوان (مثل رنگِ نقش در
      // پنل نقش‌ها) که در CSS قابل شمارش نیست. از custom property عبور
      // می‌کند تا خودِ قواعدِ CSS مالکِ نحوه‌ی مصرفش بمانند.
      style={color && on ? { '--hy-switch-track-on': color } : undefined}
      onClick={handleClick}
    >
      <span className="hy-switch__thumb" />
    </button>
  );
}
