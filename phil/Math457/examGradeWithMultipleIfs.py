

print("Enter Course Code: ")
courseCode = input("Enter Course Code: ")
print("Enter Continuous Assessment Mark: ")
markCA = float(input("Enter Continuous Assessment Mark: "))
if markCA >= 0 and markCA <= 30:
    print("Enter Examination Mark: ")
    markExam = float(input("Enter Examination Mark: "))
    if markExam >= 0 and markExam <= 70:
        markTotal = markCA + markExam
        if markTotal >= 70:
            status = "Pass"
            grade = "A"
        elif markTotal >= 60:
            status = "Pass"
            grade = "B"
        elif markTotal >= 50:
            status = "Pass"
            grade = "C"
        elif markTotal >= 40:
            status = "Pass"
            grade = "D"
        else:
            status = "Trail"
            grade = "F"
        print("\n==================" + "\nCourse: " + courseCode + "\nTotal Score: " + str(markTotal) + chr(37) + "\nGrade: " + grade + "\nStatus: " + status + "\n==================")
    else:
        print("An Invalid Mark for " + courseCode + "\n0 <= markExam <= 70")
else:
    print("An Invalid Mark for " + courseCode + "\n0 <= markCA <= 30")
