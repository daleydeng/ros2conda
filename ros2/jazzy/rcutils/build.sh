[ -f $RECIPE_DIR/package.xml ] && cp -f $RECIPE_DIR/package.xml .
mkdir build && cd build
export CFLAGS=
export CXXFLAGS=
cmake .. -DCMAKE_GENERATOR=Ninja \
        -DCMAKE_PREFIX_PATH=$PREFIX \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DBUILD_TESTING=OFF \
        -DCMAKE_C_FLAGS="-Dstatic_assert=_Static_assert" \
        && ninja install