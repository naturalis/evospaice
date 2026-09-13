"""Build taxonomy-backed trees from precomputed embedding vectors."""

from .models import BuildResult, InputPaths, TreeBuildConfig
from .pipeline import TreeBuilder, build_tree

__all__ = ["BuildResult", "InputPaths", "TreeBuildConfig", "TreeBuilder", "build_tree"]
