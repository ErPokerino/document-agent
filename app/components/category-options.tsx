"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import type { EntityDefinition } from "../../lib/types";

/** The id a categorical input names in its `list` attribute. */
export function categoryListId(entity: Pick<EntityDefinition, "name">): string {
  return `categories-${entity.name}`;
}

/**
 * The classes a categorical field may take, offered while typing.
 *
 * A closed vocabulary is its own list. An open one has none written down, so
 * the classes are whatever the labelled documents already say — read from
 * every dataset rather than assumed.
 */
export function CategoryOptions({ entities }: { entities: EntityDefinition[] }) {
  const categorical = entities.filter((entity) => entity.format === "category");
  const openNames = categorical.filter((entity) => !entity.categories?.length).map((entity) => entity.name).join("\u0000");
  const [learned, setLearned] = useState<Record<string, string[]>>({});

  useEffect(() => {
    let current = true;
    const names = openNames ? openNames.split("\u0000") : [];
    Promise.all(names.map(async (name) => [name, (await api.labelValues(name)).map((entry) => entry.value)] as const))
      .then((entries) => { if (current) setLearned(Object.fromEntries(entries)); })
      .catch(() => undefined);
    return () => { current = false; };
  }, [openNames]);

  return (
    <>
      {categorical.map((entity) => (
        <datalist id={categoryListId(entity)} key={entity.name}>
          {(entity.categories?.length ? entity.categories : learned[entity.name] ?? []).map((value) => (
            <option value={value} key={value} />
          ))}
        </datalist>
      ))}
    </>
  );
}
