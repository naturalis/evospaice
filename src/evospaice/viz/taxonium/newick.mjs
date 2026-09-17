// SPDX-License-Identifier: GPL-3.0-only

function skipWhitespace(state) {
  while (/\s/.test(state.text[state.position] || "")) {
    state.position += 1;
  }
}

function readDescriptor(state) {
  const start = state.position;
  let commentDepth = 0;
  let inQuote = false;

  while (state.position < state.text.length) {
    const character = state.text[state.position];
    if (inQuote) {
      if (character === "'" && state.text[state.position + 1] === "'") {
        state.position += 2;
        continue;
      }
      if (character === "'") {
        inQuote = false;
      }
    } else if (character === "'") {
      inQuote = true;
    } else if (character === "[") {
      commentDepth += 1;
    } else if (character === "]" && commentDepth > 0) {
      commentDepth -= 1;
    } else if (commentDepth === 0 && ",();".includes(character)) {
      break;
    }
    state.position += 1;
  }

  if (inQuote || commentDepth) {
    throw new Error("The tree contains an unterminated quote or comment");
  }
  return state.text.slice(start, state.position).trim();
}

function parseNode(state) {
  skipWhitespace(state);
  const children = [];
  if (state.text[state.position] === "(") {
    state.position += 1;
    children.push(parseNode(state));
    while (true) {
      skipWhitespace(state);
      const character = state.text[state.position];
      if (character === ",") {
        state.position += 1;
        children.push(parseNode(state));
      } else if (character === ")") {
        state.position += 1;
        break;
      } else {
        throw new Error(`Expected ',' or ')' at character ${state.position}`);
      }
    }
  }

  const descriptor = readDescriptor(state);
  if (!children.length && !descriptor) {
    throw new Error(`Expected a node at character ${state.position}`);
  }
  const node = { children, descriptor, parent: null, numTips: 0, y: 0, taxoniumId: -1 };
  children.forEach((child) => {
    child.parent = node;
  });
  return node;
}

function postorder(root) {
  const nodes = [];
  const stack = [[root, false]];
  while (stack.length) {
    const [node, expanded] = stack.pop();
    if (expanded) {
      nodes.push(node);
    } else {
      stack.push([node, true]);
      for (let index = node.children.length - 1; index >= 0; index -= 1) {
        stack.push([node.children[index], false]);
      }
    }
  }
  return nodes;
}

export function parseNewickTopology(text) {
  const state = { text, position: 0 };
  const root = parseNode(state);
  skipWhitespace(state);
  if (state.text[state.position] !== ";") {
    throw new Error(`Expected ';' at character ${state.position}`);
  }
  state.position += 1;
  skipWhitespace(state);
  if (state.position !== state.text.length) {
    throw new Error(`Unexpected content at character ${state.position}`);
  }

  const nodes = postorder(root);
  const tipCount = nodes.filter((node) => !node.children.length).length;
  const tipScale = Math.max(tipCount - 1, 1);
  let tipIndex = 0;
  nodes.forEach((node) => {
    if (!node.children.length) {
      node.numTips = 1;
      node.y = tipIndex / tipScale;
      tipIndex += 1;
    } else {
      node.numTips = node.children.reduce((total, child) => total + child.numTips, 0);
      node.y = (node.children[0].y + node.children.at(-1).y) / 2;
    }
  });

  const taxoniumOrder = nodes
    .map((node, index) => ({ node, index }))
    .sort((left, right) => left.node.y - right.node.y || left.index - right.index)
    .map(({ node }) => node);
  taxoniumOrder.forEach((node, index) => {
    node.taxoniumId = index;
  });

  return {
    root,
    tipCount,
    byId: new Map(taxoniumOrder.map((node) => [node.taxoniumId, node])),
  };
}

export function findMrca(first, second) {
  const firstAncestors = new Set();
  for (let node = first; node; node = node.parent) {
    firstAncestors.add(node);
  }
  for (let node = second; node; node = node.parent) {
    if (firstAncestors.has(node)) {
      return node;
    }
  }
  throw new Error("Selected nodes do not belong to the same tree");
}

function descriptorLabel(descriptor) {
  const value = descriptor.trimStart();
  if (!value.startsWith("'")) {
    const end = value.search(/[:[]/);
    return (end < 0 ? value : value.slice(0, end)).trim();
  }

  let label = "";
  for (let position = 1; position < value.length; position += 1) {
    const character = value[position];
    if (character !== "'") {
      label += character;
    } else if (value[position + 1] === "'") {
      label += "'";
      position += 1;
    } else {
      return label;
    }
  }
  throw new Error("The tree contains an unterminated quoted label");
}

export function propagateTipMemberships(root, membershipsByTip) {
  const membershipsByNode = new Map();
  postorder(root).forEach((node) => {
    const memberships = new Set();
    if (!node.children.length) {
      (membershipsByTip.get(descriptorLabel(node.descriptor)) || [])
        .forEach((sample) => memberships.add(sample));
    } else {
      node.children.forEach((child) => {
        (membershipsByNode.get(child) || [])
          .forEach((sample) => memberships.add(sample));
      });
    }
    if (memberships.size) {
      membershipsByNode.set(node, [...memberships]);
    }
  });
  return membershipsByNode;
}

export function filterToTipLabels(root, selectedLabels) {
  function cloneSelected(node) {
    if (!node.children.length) {
      if (!selectedLabels.has(descriptorLabel(node.descriptor))) {
        return null;
      }
      return { ...node, children: [], parent: null, numTips: 1 };
    }

    const children = node.children.map(cloneSelected).filter(Boolean);
    if (!children.length) {
      return null;
    }
    const clone = {
      ...node,
      children,
      parent: null,
      numTips: children.reduce((total, child) => total + child.numTips, 0),
    };
    children.forEach((child) => {
      child.parent = clone;
    });
    return clone;
  }

  const filtered = cloneSelected(root);
  if (!filtered) {
    throw new Error("None of the selected tips occur in the tree");
  }
  return filtered;
}

function serializeNode(node) {
  const children = node.children.length
    ? `(${node.children.map(serializeNode).join(",")})`
    : "";
  return children + node.descriptor;
}

function appendMetadata(descriptor, metadata) {
  const payload = Object.entries(metadata)
    .map(([key, value]) => `${key}=${value}`)
    .join(",");
  let commentStart = -1;
  let commentEnd = -1;
  let currentStart = -1;
  let commentDepth = 0;
  let inQuote = false;

  for (let position = 0; position < descriptor.length; position += 1) {
    const character = descriptor[position];
    if (inQuote) {
      if (character === "'" && descriptor[position + 1] === "'") {
        position += 1;
      } else if (character === "'") {
        inQuote = false;
      }
    } else if (character === "'") {
      inQuote = true;
    } else if (character === "[") {
      if (commentDepth === 0) {
        currentStart = position;
      }
      commentDepth += 1;
    } else if (character === "]" && commentDepth > 0) {
      commentDepth -= 1;
      if (commentDepth === 0) {
        commentStart = currentStart;
        commentEnd = position;
      }
    }
  }

  if (commentEnd < 0) {
    return `${descriptor}[&${payload}]`;
  }
  const commentBody = descriptor.slice(commentStart + 1, commentEnd);
  const separator = commentBody.trim() ? "," : "&";
  return `${descriptor.slice(0, commentEnd)}${separator}${payload}` +
    `${descriptor.slice(commentEnd)}`;
}

function serializeNodeWithMemberships(node, membershipsByNode) {
  const children = node.children.length
    ? `(${node.children
      .map((child) => serializeNodeWithMemberships(child, membershipsByNode))
      .join(",")})`
    : "";
  const memberships = membershipsByNode.get(node) || [];
  if (!memberships.length) {
    return children + node.descriptor;
  }
  const sample = memberships.length > 1
    ? `Overlap (${memberships.length})`
    : memberships[0];
  return children + appendMetadata(node.descriptor, {
    sample,
    sample_memberships: memberships.join(" | "),
    overlap_count: memberships.length,
  });
}

export function serializeSubtree(root) {
  return `${serializeNode(root)};`;
}

export function serializeTreeWithMemberships(root, membershipsByNode) {
  return `${serializeNodeWithMemberships(root, membershipsByNode)};`;
}