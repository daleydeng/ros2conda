## Building Principles
- when building package A, at the same time package `B` appears in `build_export` sections in `A`'s `package.xml`, then append `B` into `A-devel` virtual subpackage
- when building package `A`, at the same time package `B` appears in `build*` sections in `A`'s `package.xml`, then use `B-devel` virtual subpackage