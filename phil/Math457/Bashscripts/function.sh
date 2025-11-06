#!/bin/bash

Rectangular_Area() {
	area=$(($1 * $2 * $3))|bc
echo "Area is : $area"
}

Rectangular_Area 10 20 15

