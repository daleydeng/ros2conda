./tools/ros2_gen_recipe.py $1
sleep 1
rattler-build build --recipe $1
