% Note: The first function listed is executed. main() is not a special function in Matlab/Octave.
%function examGrade()
%disp('Enter Course Code: ');
clc
courseCode = input('Enter Course Code: ', 's');
%disp('Enter Continuous Assessment Mark: ');
markCA = input('Enter Continuous Assessment Mark: ');
if markCA >= 0 && markCA <= 30
    %disp('Enter Examination Mark: ');
    markExam = input('Enter Examination Mark: ');
    if markExam >= 0 && markExam <= 70
        markTotal = markCA + markExam;
        if markTotal >= 70
            status = 'Pass';
            grade = 'A';
        elseif markTotal >= 60
            status = 'Pass';
            grade = 'B';
        elseif markTotal >= 50
            status = 'Pass';
            grade = 'C';
        elseif markTotal >= 40
            status = 'Pass';
            grade = 'D';
        else
            status = 'Trail';
            grade = 'F';
        end
        disp(['===================', char(13), 'Course: ', courseCode, char(13),... 
            'Total Score: ', num2str(markTotal), char(37), char(13),...
            'Grade: ', grade, char(13), 'Status: ', status, char(13),...
            '===================']);
    else
        disp(['An Invalid Mark for ', courseCode, char(13), '0 <= markExam <= 70']);
    end
else
    disp(['An Invalid Mark for ', courseCode, char(13), '0 <= markCA <= 30']);
end
%end
