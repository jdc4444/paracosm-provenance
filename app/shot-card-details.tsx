import type { ReactNode } from "react";

type ShotCardDetailsProps = {
  chapter: string;
  name: string;
  duration: number;
  cutNumber: string;
  timecode: string;
  description: string;
  tags?: ReactNode;
};


export function ShotCardDetails({
  chapter,
  name,
  duration,
  cutNumber,
  timecode,
  description,
  tags,
}: ShotCardDetailsProps) {
  return (
    <div className="shot-card-details">
      <div className="shot-card-primary">
        <span>{chapter}</span>
        <strong>{name}</strong>
        <i>{duration.toFixed(1)}s</i>
      </div>
      <div className="shot-card-secondary">
        <span>{cutNumber}</span>
        <time>{timecode}</time>
      </div>
      <p>{description}</p>
      {tags ? <div className="shot-card-tags">{tags}</div> : null}
    </div>
  );
}
