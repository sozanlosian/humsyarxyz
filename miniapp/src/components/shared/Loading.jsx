export function Spinner({
  size = 24,
  color = 'var(--acc2)',
  label = 'در حال بارگذاری',
}) {
  const borderSize =
    Math.max(
      2,
      Math.round(
        size / 10
      )
    );

  return (
    <span
      role="status"
      aria-label={label}
      style={{
        display:
          'inline-block',

        width:
          size,

        height:
          size,

        flexShrink:
          0,

        border:
          `${borderSize}px solid var(--bd)`,

        borderTopColor:
          color,

        borderRadius:
          '50%',

        animation:
          'spin .7s linear infinite',
      }}
    />
  );
}


export function LoadingScreen() {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position:
          'relative',

        display:
          'flex',

        alignItems:
          'center',

        justifyContent:
          'center',

        width:
          '100%',

        minHeight:
          '100dvh',

        overflow:
          'hidden',

        color:
          'var(--tx)',

        /* شفاف — لایه‌ی fixed مشترک body؛
           دقیقاً همان تصویرِ بدون seam بین
           لودینگ و محتوای نهایی */
        background: 'transparent',
      }}
    >
      <div
        style={{
          position:
            'absolute',

          width:
            220,

          height:
            220,

          borderRadius:
            '50%',

          background:
            'var(--soft-acc)',

          filter:
            'blur(45px)',

          transform:
            'translateY(-35px)',
        }}
      />

      <div
        className="fade-up"
        style={{
          position:
            'relative',

          display:
            'flex',

          flexDirection:
            'column',

          alignItems:
            'center',

          gap:
            13,

          textAlign:
            'center',
        }}
      >
        <div
          style={{
            display:
              'grid',

            width:
              76,

            height:
              76,

            placeItems:
              'center',

            background:
              'var(--grad-brand)',

            border:
              '1px solid var(--bd)',

            borderRadius: 'var(--r-xl)',

            boxShadow:
              'var(--shd-glow)',

            fontSize:
              37,
          }}
        >
          🩺
        </div>

        <div>
          <div
            style={{
              fontSize: 'var(--fs-xl)',

              fontWeight:
                900,

              letterSpacing:
                '-.4px',
            }}
          >
            هامزیار
          </div>

          <div
            style={{
              color:
                'var(--txm)',

              fontSize: 'var(--fs-cap)',

              marginTop:
                3,
            }}
          >
            همراه هوشمند مسیر پزشکی
          </div>
        </div>

        <Spinner size={26} />

        <span
          style={{
            color:
              'var(--txm)',

            fontSize: 'var(--fs-cap)',
          }}
        >
          در حال آماده‌سازی اطلاعات...
        </span>
      </div>
    </div>
  );
}


export function SkeletonLine({
  width = '100%',
  w,
  height = 14,
  h,
  marginTop = 0,
  mt,
}) {
  return (
    <div
      className="skeleton"
      aria-hidden="true"
      style={{
        width:
          w ?? width,

        height:
          h ?? height,

        marginTop:
          mt ?? marginTop,
      }}
    />
  );
}


/* SkeletonCardِ عمومی حذف شد (موج ۴.۴۰) —
   تمام صفحات از کامپوزیت‌های اختصاصیِ
   `skeletons.jsx` با همان پایه‌ی `.skeleton`
   و بیلدرهای مشترک استفاده می‌کنند؛
   SkeletonLine همچنان بلوک پایه است */

/* اسکلت «کارنامه من» — موج ۴.۳۰
   قانون: کرومِ اسکلت (کلاس کارت، بوردر، گلو،
   ابعاد) پیکسل‌به‌پیکسل با نسخه‌ی نهایی یکی
   است؛ لحظه‌ی تعویض هیچ تغییری در بدنه دیده
   نمی‌شود و فقط محتوای داخلی «کامل می‌شود» —
   دیگر فیدِ شفافیت روی کارتِ بوردردار لازم
   نیست و همان ریشه‌ی فلش سفید حذف می‌شود */
export function GradesSkeleton() {
  return (
    <div
      aria-hidden="true"
      style={{
        display: 'grid',
        gap: 12,
      }}
    >
      {/* هیرو — دقیقاً همان کروم نسخه‌ی نهایی */}
      <section
        className="card card-glow hero-card"
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 15,
          }}
        >
          {/* حلقه‌ی ۹۰px — شیم دایره + هسته */}
          <div
            style={{
              position: 'relative',
              display: 'grid',
              flex: '0 0 90px',
              height: 90,
              placeItems: 'center',
              borderRadius: '50%',
            }}
          >
            <div
              className="skeleton"
              style={{
                position: 'absolute',
                inset: 0,
                borderRadius: '50%',
              }}
            />

            <div
              style={{
                position:
                  'relative',
                display: 'grid',
                width: 72,
                height: 72,
                placeItems:
                  'center',
                background:
                  'var(--surf)',
                borderRadius:
                  '50%',
              }}
            >
              <div
                style={{
                  display: 'grid',
                  gap: 5,
                  justifyItems:
                    'center',
                }}
              >
                <SkeletonLine
                  width={36}
                  height={15}
                />
                <SkeletonLine
                  width={24}
                  height={8}
                />
              </div>
            </div>
          </div>

          <div style={{ flex: 1 }}>
            <SkeletonLine
              width={84}
              height={10}
            />

            <div
              style={{ marginTop: 'var(--sp-2)' }}
            >
              <SkeletonLine
                width={70}
                height={15}
              />
            </div>

            <div
              style={{ marginTop: 'var(--sp-2)' }}
            >
              <SkeletonLine
                width={150}
                height={9}
              />
            </div>

            <div
              style={{ marginTop: 5 }}
            >
              <SkeletonLine
                width={118}
                height={9}
              />
            </div>
          </div>
        </div>
      </section>

      {/* دو کارت آمار کوچک (grid2) */}
      <section className="grid2">
        {[0, 1].map((key) => (
          <div
            key={key}
            className="card"
            style={{
              textAlign: 'center',
              padding: 12,
            }}
          >
            <div
              style={{
                display: 'grid',
                gap: 6,
                justifyItems:
                  'center',
              }}
            >
              <SkeletonLine
                width={34}
                height={16}
              />
              <SkeletonLine
                width={54}
                height={9}
              />
            </div>
          </div>
        ))}
      </section>

      {/* تیتر بخش جزئیات */}
      <div
        className="sec-title"
        style={{ marginTop: 'var(--sp-1)' }}
      >
        <SkeletonLine
          width={100}
          height={11}
        />
      </div>

      {/* سه ردیف نمره — همان ژئومتری GradeRow */}
      <section
        style={{
          display: 'grid',
          gap: 9,
        }}
      >
        {[0, 1, 2].map((key) => (
          <article
            key={key}
            className="card"
            style={{ padding: 13 }}
          >
            <div
              style={{
                display: 'flex',
                alignItems:
                  'center',
                gap: 11,
              }}
            >
              <div
                className="skeleton"
                style={{
                  width: 54,
                  height: 54,
                  flexShrink: 0,
                  borderRadius: 'var(--r-lg)',
                }}
              />

              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                }}
              >
                <SkeletonLine
                  width="62%"
                  height={12}
                />

                <div
                  style={{
                    marginTop: 5,
                  }}
                >
                  <SkeletonLine
                    width="44%"
                    height={9}
                  />
                </div>

                <div
                  style={{
                    marginTop: 5,
                  }}
                >
                  <SkeletonLine
                    width="34%"
                    height={8}
                  />
                </div>
              </div>

              <div
                style={{
                  display: 'grid',
                  gap: 5,
                  justifyItems:
                    'center',
                }}
              >
                <SkeletonLine
                  width={20}
                  height={18}
                />
                <SkeletonLine
                  width={34}
                  height={8}
                />
              </div>
            </div>

            <div
              style={{
                marginTop: 11,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent:
                    'space-between',
                  marginBottom: 5,
                }}
              >
                <SkeletonLine
                  width={62}
                  height={8}
                />
                <SkeletonLine
                  width={26}
                  height={8}
                />
              </div>

              <div className="pbar">
                <div
                  className="skeleton"
                  style={{
                    width: '100%',
                    height: '100%',
                    borderRadius:
                      'inherit',
                  }}
                />
              </div>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}

