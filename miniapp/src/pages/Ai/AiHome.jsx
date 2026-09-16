import {
  useParams,
} from 'react-router-dom';

import AiChat from './AiChat';
import AiHistory from './AiHistory';


/* ─────────────────────────────────────────────
   نقطه‌ی ورود هوشیار
   /ai         → فهرست تاریخچه‌ی گفت‌وگوها
   /ai/c/:id   → خودِ گفت‌وگو

   key روی convId باعث ری‌ماونتِ صفحه‌ی چت بین
   رشته‌ها می‌شود — هر رشته با وضعیتِ کاملاً
   تمیز (کامپوزر، رکوردر، حافظه‌ی reveal و…)
   باز می‌شود؛ موقعیت اسکرول هر رشته در Mapِ
   سطح‌ماژول AiChat محفوظ می‌ماند.
───────────────────────────────────────────── */


export default function AiHome() {
  const { convId } = useParams();

  if (!convId) {
    return <AiHistory />;
  }

  return (
    <AiChat key={convId} />
  );
}
