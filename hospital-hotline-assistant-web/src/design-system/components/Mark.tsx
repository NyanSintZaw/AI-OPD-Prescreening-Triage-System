import { memo, useEffect, useRef } from 'react';
import type { SVGProps } from 'react';
import { NongMali } from './NongMali';
import { playMark, type MarkMotion } from '../motion';

export interface MarkProps extends Omit<SVGProps<SVGSVGElement>, 'children'> {
  /** Pixel size of the square mark. */
  size?: number;
  /** Stamens shown — the bud doubles as a progress signal: 0 = start, 1 = in progress, 3 = complete (default). */
  stage?: 0 | 1 | 3;
  /** `teal` (default) on light surfaces; `gold` is the signature cut for dark teal surfaces. */
  tone?: 'teal' | 'gold';
  /** Play one of the bud's approved motions on mount: draw (loading), filled
   *  (reveal), hand (signature sketch) or grow (step complete). Skipped under
   *  prefers-reduced-motion. */
  motion?: Extract<MarkMotion, 'budDraw' | 'budFilled' | 'budHand' | 'budGrow'>;
}

/**
 * The bud — MALI's secondary mark. Progress, loading, favicons, anywhere smaller than 40px.
 * Fixed brand palette (teal body, cream petal, gold stamens) — never recolour.
 */
function MarkImpl({ size = 24, stage = 3, tone = 'teal', motion, ...rest }: MarkProps) {
  const ref = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (!motion) return;
    /* Next frame, not this one: the mark's paths are written with
       dangerouslySetInnerHTML, and on some hosts they are not queryable yet
       when the effect fires — the motion would then animate nothing. */
    let h: { cancel: () => void } | undefined;
    const raf = requestAnimationFrame(() => {
      h = playMark(ref.current, motion);
    });
    return () => {
      cancelAnimationFrame(raf);
      h?.cancel();
    };
  }, [motion, stage, tone]);
  return (
    <svg ref={ref} width={size} height={size} viewBox="-40 -39 304 296" aria-hidden="true" {...rest}>
      <path d={PETAL} fill="#DDE8DF" fillRule="evenodd" />
      <path d={BODY} fill={tone === 'gold' ? '#E5B25D' : '#58A19D'} fillRule="evenodd" />
      {stage >= 1 && (
        <g stroke="#DBB566" strokeWidth={3.3} fill="none" strokeLinecap="round">
          <path d="M111.5,108.2 L111.5,57.3" />
          {stage >= 3 && <path d="M111.5,108.2 Q100.6,92.1 96.2,74.7" />}
          {stage >= 3 && <path d="M111.5,108.2 Q122.4,92.1 126.8,74.7" />}
        </g>
      )}
      {stage >= 1 && (
        <g fill="#DBB566">
          <circle cx={111.5} cy={54.6} r={5.6} />
          {stage >= 3 && <circle cx={96.2} cy={72} r={4.7} />}
          {stage >= 3 && <circle cx={126.8} cy={72} r={4.7} />}
        </g>
      )}
    </svg>
  );
}

const PETAL = 'M130,50.5Q131.5,51 136.5,58.5Q141.5,66 145.5,77.5Q149.5,89 149,95Q148.5,101 144.5,107Q140.5,113 131.8,120.3Q123,127.5 118,133Q113,138.5 111.5,138.5Q110,138.5 93.8,122.8Q77.5,107 76.5,105Q75.5,103 76.3,100.8Q77,98.5 86,94.5Q95,90.5 102,85.5Q109,80.5 115.3,72.8Q121.5,65 125,58Q128.5,51 128.5,50.5Q128.5,50 130,50.5Z';
const BODY = 'M111.3,2.8Q113,2.5 114.8,4.3Q116.5,6 131.5,25Q146.5,44 152.5,54.5Q158.5,65 161,71.5Q163.5,78 164.5,83.5Q165.5,89 165,96Q164.5,103 163,106.5Q161.5,110 159,113Q156.5,116 157,116.5Q157.5,117 153.3,121.3Q149,125.5 139.5,132.5Q130,139.5 121.3,148.8Q112.5,158 110,164.5Q107.5,171 108.8,172.3Q110,173.5 111.8,173.3Q113.5,173 113.5,167.5Q113.5,162 115.3,160.8Q117,159.5 119.3,165.3Q121.5,171 120.5,175Q119.5,179 117.3,180.8Q115,182.5 110,182Q105,181.5 103.3,179.3Q101.5,177 102,171Q102.5,165 109,154.5Q115.5,144 122.3,137.3Q129,130.5 140.8,121.8Q152.5,113 155.5,106.5Q158.5,100 158.5,93Q158.5,86 157,80.5Q155.5,75 151.5,66.5Q147.5,58 142,50Q136.5,42 125,28Q113.5,14 111.8,13.8Q110,13.5 94.8,32.3Q79.5,51 73,64Q66.5,77 65.5,81.5Q64.5,86 64.5,94Q64.5,102 66.5,106.5Q68.5,111 71.3,113.8Q74,116.5 75,116.5Q76,116.5 83,122Q90,127.5 97.3,134.3Q104.5,141 106.5,144Q108.5,147 107.3,149.3Q106,151.5 85.3,134.3Q64.5,117 65,116.5Q65.5,116 63,112Q60.5,108 59,102Q57.5,96 59,85.5Q60.5,75 65,65Q69.5,55 79.5,40.5Q89.5,26 99.3,14.8Q109,3.5 109.3,3.3Q109.5,3 111.3,2.8Z M30.3,129.8Q39,129.5 47.5,131Q56,132.5 65,136Q74,139.5 84.3,146.8Q94.5,154 94.5,155.5Q94.5,157 93.8,157.3Q93,157.5 82,151.5Q71,145.5 61,142.5Q51,139.5 39,138.5Q27,137.5 23.3,138.8Q19.5,140 20,144Q20.5,148 25,156Q29.5,164 37.3,171.8Q45,179.5 51,183.5Q57,187.5 66,191Q75,194.5 75.8,196.3Q76.5,198 71.3,197.8Q66,197.5 56.5,193.5Q47,189.5 39.5,184Q32,178.5 27.3,173.3Q22.5,168 19,162.5Q15.5,157 13,150Q10.5,143 10.5,138.5Q10.5,134 12.8,132.3Q15,130.5 18,130.5Q21,130.5 21.3,130.3Q21.5,130 30.3,129.8Z M191.3,129.8Q200,129.5 203.5,130Q207,130.5 208.8,131.8Q210.5,133 210.5,139.5Q210.5,146 207.5,153Q204.5,160 201.5,164.5Q198.5,169 192.3,175.3Q186,181.5 179.5,186Q173,190.5 166,193.5Q159,196.5 152.5,197.5Q146,198.5 145.8,197.3Q145.5,196 146.3,195.3Q147,194.5 150.5,193.5Q154,192.5 161.5,188.5Q169,184.5 178.8,176.3Q188.5,168 192.5,162.5Q196.5,157 198.5,153Q200.5,149 201.5,144.5Q202.5,140 201.8,139.3Q201,138.5 197,138Q193,137.5 182,138.5Q171,139.5 160,143Q149,146.5 139.5,152Q130,157.5 128.8,157.3Q127.5,157 128.8,154.3Q130,151.5 141.5,144.5Q153,137.5 160,135Q167,132.5 174.5,131.5Q182,130.5 182.3,130.3Q182.5,130 191.3,129.8Z';

export interface WordmarkProps {
  /** Rendered height of the wordmark in px. */
  height?: number;
  /** `th` renders มะลิ (Thai primary), `en` renders MALI. */
  lang?: 'en' | 'th';
  /** Lowercase friendly cut with the gold dot — kiosk welcome, mascot contexts. */
  friendly?: boolean;
  /** Product suffix after the name ("Prescreening"). */
  product?: string;
  /** `dark` reverses the lockup for deep-teal surfaces: paper letters, gold accent, signature bud. */
  tone?: 'light' | 'dark';
  /** Which mark sits in the lockup. `nong` (default) — Nong Mali is the product's main logo.
   *  `bud` for compact contexts (dense headers, favicons-adjacent). Dark tone always uses the signature bud. */
  mark?: 'nong' | 'bud';
}

/** MALI wordmark — Anuphan bold, the L (or ล) in teal; friendly cut golds the i-dot (Thai: the vowel). */
export function Wordmark({ height = 24, lang = 'en', friendly = false, product, tone = 'light', mark = 'nong' }: WordmarkProps) {
  const VOWEL_I = '\u0E34';
  return (
    <span className={tone === 'dark' ? 'mali-wordmark mali-wordmark--dark' : 'mali-wordmark'} style={{ fontSize: height }}>
      {tone === 'dark' ? (
        <Mark size={height * 1.15} tone="gold" />
      ) : mark === 'nong' ? (
        <NongMali size={height * 1.6} />
      ) : (
        <Mark size={height * 1.15} />
      )}
      <span className="mali-wordmark__name">
        {lang === 'th' ? (
          friendly ? (
            <>มะล<span className="mali-wordmark__gold">{VOWEL_I}</span></>
          ) : (
            <>มะ<span className="mali-wordmark__accent">ล</span>{VOWEL_I}</>
          )
        ) : friendly ? (
          <>mal<span className="mali-wordmark__i">ı<span className="mali-wordmark__idot" aria-hidden="true" /></span></>
        ) : (
          <>MA<span className="mali-wordmark__accent">L</span>I</>
        )}
      </span>
      {product && <span className="mali-wordmark__product">{product}</span>}
    </span>
  );
}

/* Memoised for the same reason as NongMali: a parent re-render would replace
   the animated path nodes and orphan any running motion. */
export const Mark = memo(MarkImpl);
