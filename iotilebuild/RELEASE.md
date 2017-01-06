# Release Notes

All major changes in each released version of IOTileBuild are listed here.

## 2.2.6

- Update autobuild_release to allow it to be called manually from an SConstruct file

## 2.2.5

- Fix bug building components that specified a version for their dependencies
- Add extensive test coverage of dependency resolution
- Update with dependency check function to test and make sure all installed dependencies
  are compatible with each other.

## 2.2.4

- Update RegistryResolver to properly check the version of the component it found in the registry
  to make sure that it matches.

## 2.2.3

- Fix DependencyResolverChain to properly report when its updating vs installing a new component

## 2.2.2

- Fix bug in DependencyResolverChain where checking if a component is up to date didn't work
  if there were multiple dependency resolvers in the chain.

## 2.2.1

- Update iotile release to make the path optional
- Update docstring for DependencyResolver

## 2.2.0

- Add entry point for inserting release providers that allow releasing IOTile components.
- Add iotile release command for releasing an IOTile using a sequence of release providers
- Update minimum required iotile-core version to 3.3.0 based on the need for release_steps
  parsing in the IOTile object.

## 2.1.0

- Add entry point for inserting DependencyResolvers into the lookup chain
  used to find dependencies for a tile.  The entry point is iotile.build.depresolver.
  See iotile.build.dev.resolvers.__init__.py for the entry point format
- Add DependencyResolverChain unit test
- Add missing dependency on toposort

## 2.0.5

- Improve error processing in dependencies with documentation (Issue #48)

## 2.0.4

- Fix error processing dependencies in documentation (Issue #48)