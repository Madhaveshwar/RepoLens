import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";

interface HealthScoreRingProps {
  score: number | null;
  size?: number;
  strokeWidth?: number;
  label?: string;
  animate?: boolean;
  unavailable?: boolean;
}

const getScoreColor = (score: number): string => {
  if (score >= 90) return "#22C55E";
  if (score >= 70) return "#4F7CFF";
  if (score >= 50) return "#F59E0B";
  return "#EF4444";
};

const getScoreLabel = (score: number): string => {
  if (score >= 90) return "Excellent";
  if (score >= 75) return "Good";
  if (score >= 60) return "Fair";
  if (score >= 40) return "Needs Work";
  return "Poor";
};

export const HealthScoreRing: React.FC<HealthScoreRingProps> = ({
  score,
  size = 160,
  strokeWidth = 12,
  animate = true,
  unavailable = false,
}) => {
  const safeScore = score ?? 0;
  const [displayScore, setDisplayScore] = useState(animate ? 0 : safeScore);
  const color = getScoreColor(safeScore);
  const scoreLabel = getScoreLabel(safeScore);
  // label is kept in the interface for future use

  // Animated counter
  useEffect(() => {
    if (!animate) {
      setDisplayScore(safeScore);
      return;
    }
    const duration = 1500;
    const steps = 40;
    const increment = safeScore / steps;
    let current = 0;
    let step = 0;
    const timer = setInterval(() => {
      step++;
      current += increment;
      if (step >= steps) {
        setDisplayScore(safeScore);
        clearInterval(timer);
      } else {
        setDisplayScore(Math.round(current));
      }
    }, duration / steps);
    return () => clearInterval(timer);
  }, [safeScore, animate]);

  if (unavailable) {
    return (
      <motion.div
        className="relative inline-flex items-center justify-center flex-col gap-2"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.25, 0.4, 0.25, 1] }}
      >
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={(size - strokeWidth) / 2}
            fill="none"
            stroke="#E5E7EB"
            strokeWidth={strokeWidth}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-base font-semibold text-zinc-400 text-center leading-tight px-4">
            Health score<br />unavailable
          </span>
        </div>
        <p className="text-[10px] text-zinc-400 text-center mt-1">Run a repository scan</p>
      </motion.div>
    );
  }

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (displayScore / 100) * circumference;

  return (
    <motion.div
      className="relative inline-flex items-center justify-center"
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.6, ease: [0.25, 0.4, 0.25, 1] }}
    >
      <svg width={size} height={size} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#E5E7EB"
          strokeWidth={strokeWidth}
          className="transition-colors"
        />
        {/* Score ring */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.2, ease: [0.25, 0.4, 0.25, 1], delay: 0.2 }}
          style={{
            filter: `drop-shadow(0 0 8px ${color}50)`,
          }}
        />
        {/* Glow ring overlay */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.2, ease: [0.25, 0.4, 0.25, 1], delay: 0.2 }}
          opacity={0.15}
          style={{
            filter: `blur(4px)`,
          }}
        />
      </svg>

      {/* Center content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <motion.span
          className="text-3xl font-bold font-sans"
          style={{ color }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5, duration: 0.4 }}
        >
          {displayScore}
        </motion.span>
        <motion.span
          className="text-[10px] font-semibold text-zinc-500 mt-0.5"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.7, duration: 0.4 }}
        >
          {scoreLabel}
        </motion.span>
      </div>
    </motion.div>
  );
};

export default HealthScoreRing;
