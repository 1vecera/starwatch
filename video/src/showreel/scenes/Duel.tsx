import { AbsoluteFill, useCurrentFrame } from "remotion";
import { hBlur } from "../parts/Blur";
import { Highlight, Odometer, Words } from "../parts/Kinetic";
import { Card, Stage } from "../parts/Stage";
import { kick, track, whip } from "../parts/track";
import { asset, C, display, easeIn, expoOut, label, pop, ramp } from "../theme";
import { beatFrame as F } from "../timing";
import { WHIP_AT } from "./Flight";

// The spine: Prague's candidate with the most reach and its candidate with the most votes, then both
// head to head. Portraits are element screenshots of each Spotlight page (take parts); every number is
// the app's: Spotlight's video views since each account's first collected post, and the 2026 result.
const PW = 528;
const PH = 664;
const H_AT = F(40);
const CLASH = F(48);
const APPROACH = F(47);
export const DUEL_OUT = F(55.25);

// Both whips move the outgoing and the incoming layer as one camera, fastest on the beat.
const kLayer = (f: number) => (f >= APPROACH ? 0 : 1920 * (1 - whip(f, WHIP_AT)) - 1920 * whip(f, H_AT));
const hLayer = (f: number) => 1920 * (1 - whip(f, H_AT));
const land = (f: number, at: number) => 1 + 0.03 * kick(f, at + 8, 12);

type P = { x: number; y: number; ry: number; rz: number; s: number };

const Portrait: React.FC<{ who: "kastovsky" | "hlavacek"; pose: P; offset: number; speed: number }> = ({ who, pose, offset, speed }) => (
  <div style={{ position: "absolute", inset: 0, transform: `translateX(${offset}px)`, transformStyle: "preserve-3d", filter: hBlur(speed) }}>
    <Card pose={pose} w={PW} h={PH} src={asset(`parts/${who}-portrait.png`)} radius={22} position="50% 50%" />
  </div>
);

// One horizontal bar per candidate, growing outward from the centre line toward its portrait.
const Bar: React.FC<{ y: number; at: number; left: number; right: number; leftText: string; rightText: string; title: string; rightColor: string }> = ({
  y,
  at,
  left,
  right,
  leftText,
  rightText,
  title,
  rightColor,
}) => {
  const frame = useCurrentFrame();
  const grow = ramp(frame, at, at + 34, expoOut);
  const MAX = 410;
  const bar = (w: number, side: -1 | 1, color: string) => (
    <div
      style={{
        position: "absolute",
        top: y,
        height: 44,
        borderRadius: 22,
        background: color,
        left: side < 0 ? 960 - 10 - Math.max(44, w * MAX * grow) : 970,
        width: Math.max(44, w * MAX * grow),
        opacity: ramp(frame, at - 4, at + 2),
      }}
    />
  );
  return (
    <>
      <div style={{ position: "absolute", top: y - 204, left: 0, width: 1920, textAlign: "center" }}>
        <Words words={[{ text: title, at: at - 8 }]} out={DUEL_OUT} style={label(44)} />
      </div>
      <div style={{ position: "absolute", top: y - 138, right: 1920 - 924 }}>
        <Odometer value={leftText} from={at} dur={30} out={DUEL_OUT} style={display(104)} />
      </div>
      <div style={{ position: "absolute", top: y - 138, left: 996 }}>
        <Odometer value={rightText} from={at} dur={30} out={DUEL_OUT} style={display(104, rightColor)} />
      </div>
      {bar(left, -1, C.label)}
      {bar(right, 1, rightColor)}
    </>
  );
};

const Solo: React.FC<{ x: number; tag: string; first: string; last: string; at: number; views: string; votes: string; votesLabel: string; votesColor: string; out: number }> = ({
  x,
  tag,
  first,
  last,
  at,
  views,
  votes,
  votesLabel,
  votesColor,
  out,
}) => {
  const b = (beats: number) => F(at + beats);
  return (
    <>
      <div style={{ position: "absolute", left: x + 8, top: 226 }}>
        <Words words={[{ text: tag, at: b(0.75) }]} out={out} style={label(46, C.brand, 640)} />
      </div>
      <div style={{ position: "absolute", left: x + 4, top: 290 }}>
        <Words words={[{ text: first, at: b(0.25) }, { text: last, at: b(0.5) }]} out={out} style={display(116)} />
      </div>
      <div style={{ position: "absolute", left: x, top: 470 }}>
        <Odometer value={views} from={b(1)} dur={30} out={b(3.5)} style={display(240)} />
      </div>
      <div style={{ position: "absolute", left: x + 8, top: 742 }}>
        <Words words={[{ text: "video views since 2023", at: b(1.25) }]} out={b(3.5)} style={label(48)} />
      </div>
      <div style={{ position: "absolute", left: x, top: 470 }}>
        <Odometer value={votes} from={b(3.75)} dur={34} out={out} style={display(240, votesColor)} />
      </div>
      <div style={{ position: "absolute", left: x + 8, top: 742 }}>
        <Words words={[{ text: votesLabel, at: b(4.25) }]} out={out} style={label(48)} />
      </div>
    </>
  );
};

export const Duel: React.FC = () => {
  const frame = useCurrentFrame();
  const kx = kLayer(frame);
  const hx = hLayer(frame);
  // Kaštovský: solo on the left; off frame with the whip; from beat 47 he flies back in to meet
  // Hlaváček in the middle on the clash, and both recoil to their corners on a spring.
  const kp = track(frame, [
    { f: F(31), x: 470, y: 540, ry: 16, rz: -2, s: 1 },
    { f: APPROACH - 1, x: 470, y: 540, ry: 16, rz: -2, s: 1 },
    { f: APPROACH, x: -1450, y: 500, ry: 30, rz: -8, s: 0.8 },
    { f: CLASH, x: 770, y: 450, ry: 6, rz: 0, s: 0.72, e: easeIn },
  ]) as P;
  const hp = track(frame, [
    { f: F(39), x: 1450, y: 540, ry: -16, rz: 2, s: 1 },
    { f: APPROACH, x: 1450, y: 540, ry: -16, rz: 2, s: 1 },
    { f: CLASH, x: 1150, y: 450, ry: -6, rz: 0, s: 0.72, e: easeIn },
  ]) as P;
  const recoil = frame >= CLASH ? pop(frame, CLASH, 1.4, 1) : 0;
  const k = frame >= CLASH ? { ...kp, x: 770 + (300 - 770) * recoil, ry: 6 + 8 * recoil } : kp;
  const h = frame >= CLASH ? { ...hp, x: 1150 + (1620 - 1150) * recoil, ry: -6 - 8 * recoil } : hp;
  const squash = 1 + 0.08 * kick(frame, CLASH, 10);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ transform: `translateX(${kx}px) scale(${land(frame, WHIP_AT)})`, filter: hBlur(kx - kLayer(frame - 1)) }}>
        {frame < H_AT + 10 ? (
          <Solo x={856} tag="1st by reach in Prague" first="Tomáš" last="Kaštovský" at={32} views="25M" votes="85,284" votesLabel="votes in 2026, elected" votesColor={C.label} out={1e9} />
        ) : null}
      </AbsoluteFill>
      <AbsoluteFill style={{ transform: `translateX(${hx}px) scale(${land(frame, H_AT)})`, filter: hBlur(hx - hLayer(frame - 1)) }}>
        {frame >= H_AT - 10 && frame < APPROACH + 12 ? (
          <Solo x={146} tag="1st by votes in Prague" first="Petr" last="Hlaváček" at={40} views="999k" votes="100,907" votesLabel="votes in 2026, the most in Prague" votesColor={C.brand} out={F(47.5)} />
        ) : null}
      </AbsoluteFill>
      {frame >= CLASH ? (
        <>
          <div
            style={{
              position: "absolute",
              left: 959,
              top: 150,
              width: 2,
              height: 570 * ramp(frame, CLASH + 4, F(49), expoOut),
              background: C.hairline,
              opacity: 1 - ramp(frame, DUEL_OUT, DUEL_OUT + 8, (t) => t),
            }}
          />
          <Bar y={370} at={F(48.75)} left={1} right={0.999 / 25} leftText="25M" rightText="999k" title="Video views" rightColor={C.label} />
          <Bar y={650} at={F(50.25)} left={85284 / 100907} right={1} leftText="85,284" rightText="100,907" title="Votes in 2026" rightColor={C.brand} />
          {[
            { x: 300, name: "Tomáš Kaštovský" },
            { x: 1620, name: "Petr Hlaváček" },
          ].map((p) => (
            <div key={p.name} style={{ position: "absolute", top: 704, left: p.x - 300, width: 600, textAlign: "center" }}>
              <Words words={[{ text: p.name, at: F(48.5) }]} out={DUEL_OUT} style={label(44, C.label, 640)} />
            </div>
          ))}
          <div style={{ position: "absolute", top: 846, left: 0, width: 1920, textAlign: "center" }}>
            <Words words={[{ text: "Most", at: F(51.75) }, { text: "watched.", at: F(52) }]} out={DUEL_OUT} style={display(112)} />
            <span style={{ display: "inline-block", width: "0.3em", fontSize: 112 }} />
            <Highlight at={F(53.5)} out={DUEL_OUT} color={C.brand} size={112}>
              {(ink) => (
                <Words
                  words={[
                    { text: "Not", at: F(52.5) },
                    { text: "most", at: F(52.75) },
                    { text: "voted.", at: F(53) },
                  ]}
                  out={DUEL_OUT}
                  style={display(112, ink ? C.brand : "#FFFFFF")}
                />
              )}
            </Highlight>
          </div>
        </>
      ) : null}
      <Stage perspective={1600}>
        {frame < APPROACH ? (
          <Portrait who="kastovsky" pose={kp} offset={kx} speed={kx - kLayer(frame - 1)} />
        ) : (
          <Portrait who="kastovsky" pose={{ ...k, s: k.s * squash }} offset={0} speed={0} />
        )}
        {frame >= H_AT - 10 ? <Portrait who="hlavacek" pose={{ ...h, s: h.s * (frame >= CLASH ? squash : 1) }} offset={frame < APPROACH ? hx : 0} speed={hx - hLayer(frame - 1)} /> : null}
      </Stage>
    </AbsoluteFill>
  );
};
