import api from './api';


/* ─────────────────────────────────────────────
   خروجی‌گرفتن و اشتراک‌گذاری گفت‌وگوهای هوشیار

   - متن کامل: دانلود فایل .txt (Blob + anchor؛
     فالبک: کپی در حافظه‌ی موقت)
   - اشتراک: Web Share API با خلاصه‌ی مرتب‌شده
     (چند دورِ اول، کوتاه و شسته‌رفته) — فالبک:
     کپی همان خلاصه
───────────────────────────────────────────── */

const SHARE_MAX_CHARS = 1800;
const SHARE_ROUNDS = 3;

const ROLE_LABELS = {
  user: 'شما',
  assistant: 'هوشیار',
  model: 'هوشیار',
};


export async function fetchConvMessages(
  conversationId,
) {
  if (conversationId === 'legacy') {
    const response = await api.get(
      '/api/ai/history',
    );

    return Array.isArray(
      response.data?.messages,
    )
      ? response.data.messages
      : [];
  }

  const response = await api.get(
    `/api/ai/conversations/` +
    `${conversationId}/messages`,
  );

  return Array.isArray(
    response.data?.messages,
  )
    ? response.data.messages
    : [];
}


function formatStamp(date) {
  try {
    return date.toLocaleString('fa-IR', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });

  } catch (_) {
    return '';
  }
}


// متن کامل و مرتب برای فایل خروجی
export function buildExportText(
  item,
  messages,
) {
  const lines = [
    `گفت‌وگو: ${item.title}`,
    `تعداد پیام: ${Number(
      messages.length,
    ).toLocaleString('fa-IR')}`,
    `خروجی‌گیری: ${formatStamp(new Date())}`,
    '— هوشیار، دستیار آموزشی هامزیار',
    '═'.repeat(28),
    '',
  ];

  messages.forEach((message) => {
    lines.push(
      `▸ ${
        ROLE_LABELS[message.role] || 'پیام'
      }:`,
    );

    lines.push(
      String(message.text || '').trim(),
    );

    lines.push('');
  });

  return lines.join('\n');
}


// خلاصه‌ی کوتاه و شسته‌رفته برای اشتراک‌گذاری
export function buildShareText(
  item,
  messages,
) {
  const pairs = [];

  for (
    let i = 0;
    i < messages.length && pairs.length < SHARE_ROUNDS;
    i += 1
  ) {
    pairs.push(messages[i]);
  }

  const chunks = [
    `💬 ${item.title}`,
    '',
  ];

  pairs.forEach((message) => {
    const text = String(
      message.text || '',
    ).trim();

    chunks.push(
      `${
        ROLE_LABELS[message.role] || 'پیام'
      }: ${
        text.length > 240
          ? `${text.slice(0, 240)}…`
          : text
      }`,
    );

    chunks.push('');
  });

  chunks.push(
    `⋯ و ${
      Math.max(
        0,
        messages.length - pairs.length,
      ).toLocaleString('fa-IR')
    } پیام دیگر — گفت‌وگو با هوشیار در هامزیار`,
  );

  return chunks
    .join('\n')
    .slice(0, SHARE_MAX_CHARS);
}


async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;

  } catch (_) {
    // ادامه به فالبک
  }

  try {
    const area = document.createElement(
      'textarea',
    );

    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';

    document.body.appendChild(area);

    area.focus();
    area.select();

    const ok = document.execCommand('copy');

    area.remove();

    return Boolean(ok);

  } catch (_) {
    return false;
  }
}


// نتیجه: 'shared' | 'copied' | 'failed' | 'cancelled'
export async function shareConversation(
  item,
  messages,
) {
  const text = buildShareText(item, messages);

  if (
    typeof navigator.share === 'function'
  ) {
    try {
      await navigator.share({
        title: item.title,
        text,
      });

      return 'shared';

    } catch (error) {
      // لغو توسط خودِ کاربر خطا نیست
      if (error?.name === 'AbortError') {
        return 'cancelled';
      }
    }
  }

  const copied = await copyToClipboard(text);

  return copied ? 'copied' : 'failed';
}


// دانلود فایل متنی کامل؛ در WebViewهای محدود
// به کپی در حافظه می‌افتد
// نتیجه: 'downloaded' | 'copied' | 'failed'
export async function exportConversation(
  item,
  messages,
) {
  const text = buildExportText(item, messages);

  try {
    const blob = new Blob(
      [text],
      {
        type:
          'text/plain;charset=utf-8',
      },
    );

    const url = URL.createObjectURL(blob);

    const anchor =
      document.createElement('a');

    anchor.href = url;

    anchor.download =
      `humsyar-chat-${Date.now()}.txt`;

    document.body.appendChild(anchor);

    anchor.click();

    anchor.remove();

    window.setTimeout(
      () => URL.revokeObjectURL(url),
      4000,
    );

    return 'downloaded';

  } catch (_) {
    // ادامه به فالبک
  }

  const copied = await copyToClipboard(text);

  return copied ? 'copied' : 'failed';
}
